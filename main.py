from flask import Flask, send_from_directory
from flask_cors import CORS
from flask_restful import Resource, Api, reqparse, abort
from config import debug
from db import currencies, trade_currencies, trades, eth_trades, engine
from utils import *
from contract_helper import getAddressFromPuzzleHash, getContractProgram, programToPuzzleHash, getSolutionProgram, getSecretFromSolutionProgram
from full_node_client import FullNodeClient
from helper import bytes32
from clvm.casts import int_from_bytes, int_to_bytes
from math import ceil
from eth_thing import *
import random
import blspy
import threading
import time
import json

app = Flask("yakuSwap")
cors = CORS(app, resources={r"/api/*": {"origins": "*"}})
api = Api(app)

def std_hash(b) -> bytes32:
    """
    The standard hash used in many places.
    """
    return bytes32(blspy.Util.hash256(bytes(b)))


class PingService(Resource):
	def get(self):
		return {'message': 'Pong!'}


class Currencies(Resource):
	def get(self):
		conn = engine.connect()

		s = currencies.select()
		result = conn.execute(s)
		res = []

		for row in result:
			res.append(currencyRowToJson(row))

		conn.close()
		return {'currencies': res}


class ConnectionStatus(Resource):
	def get(self):
		conn = engine.connect()

		s = currencies.select()
		result = conn.execute(s)
		res = []

		for row in result:
			prefix = row[0]
			client = FullNodeClient(
				row[9], # ssl_directory
				row[7], # host
				row[8] # port
			)

			api_resp = client.getBlockchainState()
			if api_resp.get("blockchain_state", -1) == -1:
				res.append({"currency": prefix, "status": "not_connected"})
			else:
				if api_resp["blockchain_state"]["sync"]["synced"]:
					res.append({"currency": prefix, "status": "connected"})
				else:
					res.append({"currency": prefix, "status": "not_synced"})

		conn.close()
		return {'connections': res}


class Trades(Resource):
	def get(self):
		conn = engine.connect()

		s = trades.select()
		result = conn.execute(s)
		res = []

		for row in result:
			stmt = trade_currencies.select().where(trade_currencies.c.id == row[1])
			trade_currency_one = conn.execute(stmt).all()[0]
			stmt = trade_currencies.select().where(trade_currencies.c.id == row[2])
			trade_currency_two = conn.execute(stmt).all()[0]

			res.append(tradesRowToJson(row, tradeCurrencyRowToJson(trade_currency_one), tradeCurrencyRowToJson(trade_currency_two)))

		conn.close()
		return {'trades': res}



class Currency(Resource):
	def put(self, address_prefix):
		parser = reqparse.RequestParser()
		parser.add_argument('name',type=str, required=True)
		parser.add_argument('photo_url', type=str, required=True)
		parser.add_argument('units_per_coin', type=int, required=True)
		parser.add_argument('min_fee', type=int, required=True)
		parser.add_argument('default_max_block_height', type=int, required=True)
		parser.add_argument('default_min_confirmation_height', type=int, required=True)
		parser.add_argument('host', type=str, required=True)
		parser.add_argument('port', type=int, required=True)
		parser.add_argument('ssl_directory', type=str, required=True)
		args = parser.parse_args(strict=True)

		conn = engine.connect()

		s = currencies.select().where(currencies.c.address_prefix == address_prefix)
		result = conn.execute(s)
		st = None
		if len(result.all()) == 0:
			st = currencies.insert()
		else:
			st = currencies.update().where(currencies.c.address_prefix == address_prefix)
		st = st.values(
			address_prefix = address_prefix,
			name = args['name'],
			photo_url = args['photo_url'],
			units_per_coin = args['units_per_coin'],
			min_fee = args['min_fee'],
			default_max_block_height = args['default_max_block_height'],
			default_min_confirmation_height = args['default_min_confirmation_height'],
			host = args['host'],
			port = args['port'],
			ssl_directory = args['ssl_directory']
		)
		conn.execute(st)

		conn.close()
		return {'success': True}

	def delete(self, address_prefix):
		conn = engine.connect()

		stmt = currencies.delete().where(currencies.c.address_prefix == address_prefix)
		conn.execute(stmt)

		conn.close()
		return {'success': True}

trade_threads_ids = []
trade_threads_messages = []
trade_threads_addresses = []
trade_threads_files = []
trade_threads_commands = []

# checkFunc should return True if the trade is still ok
def tradeWaitForContract(trade_index, trade, trade_currency, currency, issue_contract, wait = False, other_trade_currency = False, other_currency = False, checkFunc = False):
	global trade_threads_ids, trade_threads_messages, trade_threads_addresses, trade_threads_files

	program = getContractProgram(
		trade.secret_hash,
		trade_currency.total_amount,
		trade_currency.fee,
		trade_currency.from_address,
		trade_currency.to_address,
		trade_currency.max_block_height
	)
	programPuzzleHash = programToPuzzleHash(program)
	programAddress = getAddressFromPuzzleHash(programPuzzleHash, currency.address_prefix)
	trade_threads_files[trade_index].write(f"Waiting for contract with puzzlehash {programPuzzleHash} and address {programAddress} to be confirmed\n")
	trade_threads_files[trade_index].flush()

	full_node_client = FullNodeClient(
		currency.ssl_directory,
		currency.host,
		currency.port,
		trade_threads_files[trade_index]
	)

	amount_to_send = trade_currency.total_amount - trade_currency.fee
	amount_to_send = amount_to_send / currency.units_per_coin
	fee = trade_currency.fee / currency.units_per_coin
	
	if issue_contract:
		trade_threads_messages[trade_index] = f"Please send {amount_to_send:.12f} {currency.name} with a fee of {fee:.12f} {currency.name} to the address found below. Double-check the address before confirming the transaction - if it's wrong, your coins will be lost."
		trade_threads_addresses[trade_index] = programAddress
	else:
		trade_threads_messages[trade_index] = f"Waiting for the other human to send {amount_to_send:.12f} {currency.name} with a fee of {fee:.12f} {currency.name} to the address found below..."
		trade_threads_addresses[trade_index] = programAddress

	if wait:
		time.sleep(120)

	height = full_node_client.getBlockchainHeight()

	shouldCancel = False
	if other_trade_currency != False and other_currency != False:
		other_program = getContractProgram(
			trade.secret_hash,
			other_trade_currency.total_amount,
			other_trade_currency.fee,
			other_trade_currency.from_address,
			other_trade_currency.to_address,
			other_trade_currency.max_block_height
		)
		otherProgramPuzzleHash = programToPuzzleHash(other_program)

		other_full_node_client = FullNodeClient(
			other_currency.ssl_directory,
			other_currency.host,
			other_currency.port,
			trade_threads_files[trade_index]
		)

		other_coin_record = other_full_node_client.getContractCoinRecord(otherProgramPuzzleHash.hex(), height - 1000 - other_trade_currency.max_block_height)
		if other_coin_record == False:
			shouldCancel = True
		else:
			other_coin_block_index = other_coin_record['confirmed_block_index']
	
		trade_threads_files[trade_index].write(f"Other coin record: {other_coin_record}\nShould cancel? {shouldCancel}\n")
		trade_threads_files[trade_index].flush()

	contract_coin_record = full_node_client.getContractCoinRecord(programPuzzleHash.hex(), height - 1000 - trade_currency.max_block_height)
	while contract_coin_record == False and shouldCancel == False:
		time.sleep(60)
		height = full_node_client.getBlockchainHeight()
		if other_trade_currency != False:
			other_height = other_full_node_client.getBlockchainHeight()
			if other_height - other_coin_block_index >= other_trade_currency.max_block_height * 3 // 4 - ceil(trade_currency.min_confirmation_height * trade_currency.max_block_height / other_trade_currency.max_block_height):
				shouldCancel = True
		if checkFunc != False and not checkFunc():
			shouldCancel = True
		if not shouldCancel:
			contract_coin_record = full_node_client.getContractCoinRecord(programPuzzleHash.hex(), height - 1000 - trade_currency.max_block_height)


	if shouldCancel == False and contract_coin_record["coin"]["amount"] != trade_currency.total_amount - trade_currency.fee:
		trade_threads_files[trade_index].write(f"Trickster detected!\n")
		trade_threads_files[trade_index].flush()
		shouldCancel = True

	trade_threads_files[trade_index].write(f"Contract coin record: {contract_coin_record}\n")
	trade_threads_files[trade_index].flush()
	if shouldCancel:
		trade_threads_files[trade_index].write(f"Should cancel!\n")
		trade_threads_files[trade_index].flush()
		trade_threads_messages[trade_index] = "Cancelling trade..."
		trade_threads_addresses[trade_index] = None
	else:
		confirmed_block_index = contract_coin_record['confirmed_block_index']
		trade_threads_messages[trade_index] = "Waiting for transaction confirmation..."
		trade_threads_addresses[trade_index] = None

		height = full_node_client.getBlockchainHeight()
		while confirmed_block_index + trade_currency.min_confirmation_height > height:
			delta = height - confirmed_block_index
			trade_threads_messages[trade_index] = f"Waiting for transaction confirmation ({delta} / {trade_currency.min_confirmation_height})"
			trade_threads_addresses[trade_index] = None
			time.sleep(10)
			height = full_node_client.getBlockchainHeight()

		trade_threads_messages[trade_index] = "Commencing to next step..."
		trade_threads_addresses[trade_index] = None

	time.sleep(5)
	return shouldCancel, contract_coin_record

def lookForSolutionInBlockchain(trade_index, trade, trade_currency, currency, coin_record, other_trade_currency = False, other_currency = False):
	global trade_threads_ids, trade_threads_messages, trade_threads_addresses, trade_threads_files

	program = getContractProgram(
		trade.secret_hash,
		trade_currency.total_amount,
		trade_currency.fee,
		trade_currency.from_address,
		trade_currency.to_address,
		trade_currency.max_block_height
	)
	programPuzzleHash = programToPuzzleHash(program).hex()

	otherProgram = False
	otherProgramPuzzleHash = False
	if other_currency != False:
		otherProgram = getContractProgram(
			trade.secret_hash,
			other_trade_currency.total_amount,
			other_trade_currency.fee,
			other_trade_currency.from_address,
			other_trade_currency.to_address,
			other_trade_currency.max_block_height
		)
		otherProgramPuzzleHash = programToPuzzleHash(otherProgram).hex()

	trade_threads_files[trade_index].write(f"Loking for solution of contract with puzzlehash {programPuzzleHash}\nKeeping an eye on {otherProgramPuzzleHash}\n")
	trade_threads_files[trade_index].flush()

	full_node_client = FullNodeClient(
		currency.ssl_directory,
		currency.host,
		currency.port,
		trade_threads_files[trade_index]
	)
	other_full_node_client = False
	if other_currency != False:
		other_full_node_client = FullNodeClient(
			other_currency.ssl_directory,
			other_currency.host,
			other_currency.port,
			trade_threads_files[trade_index]
		)

	if coin_record == False:
		trade_threads_messages[trade_index] = "Getting contract coin record..."
		height = full_node_client.getBlockchainHeight()
		coin_record = full_node_client.getContractCoinRecord(programPuzzleHash, height - 1000 - trade_currency.max_block_height, True)

	trade_threads_files[trade_index].write(f"Coin record: {coin_record}\n")
	trade_threads_files[trade_index].flush()

	if coin_record == False:
		trade_threads_messages[trade_index] = "Something really strange happened..."
		trade_threads_files[trade_index].write(f"coin_record is still false?!")
		trade_threads_files[trade_index].flush()
		return False

	trade_threads_messages[trade_index] = "Getting contract solution..."
	spent_block_index = coin_record["spent_block_index"]

	other_height = False
	other_coin_record = False
	if other_full_node_client != False:
		other_height = other_full_node_client.getBlockchainHeight()
		other_coin_record = other_full_node_client.getContractCoinRecord(otherProgramPuzzleHash, other_height - 1000 - other_trade_currency.max_block_height, True)

	while spent_block_index == 0:
		time.sleep(15)
		height = full_node_client.getBlockchainHeight()
		coin_record = full_node_client.getContractCoinRecord(programPuzzleHash, height - 1000 - trade_currency.max_block_height, True)
		spent_block_index = coin_record["spent_block_index"]
		if other_full_node_client != False:
			other_height = other_full_node_client.getBlockchainHeight()
			if other_height - other_coin_record['confirmed_block_index'] >= other_trade_currency.max_block_height * 3 // 4:
				trade_threads_files[trade_index].write(f"Other currency time ran out. Exiting...")
				trade_threads_files[trade_index].flush()
				return False
		if height - coin_record['confirmed_block_index'] >= trade_currency.max_block_height * 3 // 4:
			trade_threads_files[trade_index].write(f"Main currency time ran out. Exiting...")
			trade_threads_files[trade_index].flush()
			return False

	coin = coin_record["coin"]
	coin_id = std_hash(bytes.fromhex(coin["parent_coin_info"][2:]) + bytes.fromhex(coin["puzzle_hash"][2:]) + int_to_bytes(coin["amount"])).hex()
	trade_threads_files[trade_index].write(f"Coin id: {coin_id}\nSpent block index: {spent_block_index}\n")
	trade_threads_files[trade_index].flush()
	sol = full_node_client.getCoinSolution(coin_id, spent_block_index)
	while sol == False:
		trade_threads_messages[trade_index] = "Getting contract solution (again)..."
		time.sleep(30)
		sol = full_node_client.getCoinSolution(coin_id, spent_block_index)
	
	trade_threads_files[trade_index].write(f"Solution: {sol}\n")
	trade_threads_files[trade_index].flush()
	return sol

def tradeClaimContract(trade_index, trade, trade_currency, currency, solution_program_hex, coin_record, cancel = False):
	global trade_threads_ids, trade_threads_messages, trade_threads_addresses, trade_threads_files

	if cancel:
		trade_threads_messages[trade_index] = "Preparing to cancel trade :("

	trade_threads_files[trade_index].write(f"tradeClaimContract - cancel? {cancel}\n")
	trade_threads_files[trade_index].flush()

	program = getContractProgram(
		trade.secret_hash,
		trade_currency.total_amount,
		trade_currency.fee,
		trade_currency.from_address,
		trade_currency.to_address,
		trade_currency.max_block_height
	)
	programPuzzleHash = programToPuzzleHash(program).hex()
	trade_threads_files[trade_index].write(f"tradeClaimContract - contract with puzzlehash {programPuzzleHash}\n")
	trade_threads_files[trade_index].flush()

	full_node_client = FullNodeClient(
		currency.ssl_directory,
		currency.host,
		currency.port,
		trade_threads_files[trade_index]
	)

	if coin_record == False:
		trade_threads_messages[trade_index] = "Getting contract coin record..."
		height = full_node_client.getBlockchainHeight()
		coin_record = full_node_client.getContractCoinRecord(programPuzzleHash, height - 10000 - trade_currency.max_block_height, True)
	trade_threads_files[trade_index].write(f"Coin record: {coin_record}\n")
	trade_threads_files[trade_index].flush()

	if coin_record == False:
		trade_threads_messages[trade_index] = "Contract already claimed"
		return

	trade_threads_messages[trade_index] = "Waiting for node to be synced..."
	height = full_node_client.getBlockchainHeight()
	coin = coin_record["coin"]
	trade_threads_messages[trade_index] = "Pushing transaction..."
	r = full_node_client.pushTransaction(
		program.as_bin().hex(),
		solution_program_hex,
		coin
	)
	while r == False:
		trade_threads_messages[trade_index] = "Pushing transaction again..."
		r = full_node_client.pushTransaction(
			program.as_bin().hex(),
			solution_program_hex,
			coin
		)
		time.sleep(5)
	if r == "pending":
		while r == "pending":
			trade_threads_messages[trade_index] = "The transaction was marked as PENDING - I'll push it every 30 seconds just to be sure"
			r = full_node_client.pushTransaction(
				program.as_bin().hex(),
				solution_program_hex,
				coin
			)
			time.sleep(30)
		trade_threads_messages[trade_index] = "Done! Check your wallet :)"	
	else:
		trade_threads_messages[trade_index] = "Done! Check your wallet :)"	

def shouldCancelTrade(trade_index, trade, trade_currency, currency, coin_record):
	global trade_threads_ids, trade_threads_messages, trade_threads_addresses, trade_threads_files

	trade_threads_files[trade_index].write(f"Should cancel trade?\n")
	trade_threads_files[trade_index].flush()
	program = getContractProgram(
		trade.secret_hash,
		trade_currency.total_amount,
		trade_currency.fee,
		trade_currency.from_address,
		trade_currency.to_address,
		trade_currency.max_block_height
	)
	programPuzzleHash = programToPuzzleHash(program).hex()
	trade_threads_files[trade_index].write(f"Contract with puzzlehash {programPuzzleHash}\n")
	trade_threads_files[trade_index].flush()

	full_node_client = FullNodeClient(
		currency.ssl_directory,
		currency.host,
		currency.port,
		trade_threads_files[trade_index]
	)

	if coin_record == False:
		trade_threads_messages[trade_index] = "Getting contract coin record..."
		height = full_node_client.getBlockchainHeight()
		coin_record = full_node_client.getContractCoinRecord(programPuzzleHash, height - 10000 - trade_currency.max_block_height, True)
	
	if coin_record == False:
		trade_threads_messages[trade_index] = "Contract already claimed"
		return False, False

	trade_threads_files[trade_index].write(f"Coin record: {coin_record}\n")
	trade_threads_files[trade_index].flush()
	trade_threads_messages[trade_index] = "Waiting for node to be synced..."
	height = full_node_client.getBlockchainHeight()
	trade_threads_messages[trade_index] = "Verifying height..."
	
	cancel = False

	if height - coin_record['confirmed_block_index'] >= trade_currency.max_block_height * 3 // 4:
		cancel = True

	return coin_record, cancel

def _dumpTradeCurrency(trade_index, trade_currency_one):
	global trade_threads_files
	trade_threads_files[trade_index].write(f"Addres prefix: {trade_currency_one.address_prefix}\n")
	trade_threads_files[trade_index].write(f"Fee: {trade_currency_one.fee}\n")
	trade_threads_files[trade_index].write(f"Max block height: {trade_currency_one.max_block_height}\n")
	trade_threads_files[trade_index].write(f"Min conf time: {trade_currency_one.min_confirmation_height}\n")
	trade_threads_files[trade_index].write(f"From: {trade_currency_one.from_address}\n")
	trade_threads_files[trade_index].write(f"To: {trade_currency_one.to_address}\n")
	trade_threads_files[trade_index].write(f"Total amount: {trade_currency_one.total_amount}\n\n\n")
	trade_threads_files[trade_index].flush()

def tradeCode(trade_id):
	global trade_threads_ids, trade_threads_messages, trade_threads_addresses, trade_threads_files
	trade_index = 0
	for i, v in enumerate(trade_threads_ids):
		if v == trade_id:
			trade_index = i

	trade_threads_files[trade_index].write("ONLY SHARE THE CONTENTS OF THIS FILE WITH TRUSTED PEOPLE\n")

	conn = engine.connect()

	s = trades.select().where(trades.c.id == trade_id)
	trade = conn.execute(s).all()[0]
	trade_threads_files[trade_index].write(f"Trade\n\n")
	trade_threads_files[trade_index].write(f"Trade id: {trade_id}\n")
	trade_threads_files[trade_index].write(f"Secret hash: {trade.secret_hash}\n")
	trade_threads_files[trade_index].write(f"Is Buyer?: {trade.is_buyer}\n")
	trade_threads_files[trade_index].write(f"Secret: {trade.secret}\n")
	trade_threads_files[trade_index].write(f"Step: {trade.step}\n\n\n")
	trade_threads_files[trade_index].flush()

	s = trade_currencies.select().where(trade_currencies.c.id == trade.trade_currency_one)
	trade_currency_one = conn.execute(s).all()[0]
	trade_threads_files[trade_index].write(f"Trade currency one\n\n")
	_dumpTradeCurrency(trade_index, trade_currency_one)

	s = currencies.select().where(currencies.c.address_prefix == trade_currency_one.address_prefix)
	currency_one = conn.execute(s).all()[0]

	s = trade_currencies.select().where(trade_currencies.c.id == trade.trade_currency_two)
	trade_currency_two = conn.execute(s).all()[0]
	trade_threads_files[trade_index].write(f"Trade currency two\n\n")
	_dumpTradeCurrency(trade_index, trade_currency_two)

	s = currencies.select().where(currencies.c.address_prefix == trade_currency_two.address_prefix)
	currency_two = conn.execute(s).all()[0]
	
	coin_record_one = False
	coin_record_two = False
	coming_from_step_0 = False

	shouldCancel = False

	if trade.step == 0:
		shouldCancel, coin_record_one = tradeWaitForContract(trade_index, trade, trade_currency_one, currency_one, trade.is_buyer, True)

		s = trades.update().where(trades.c.id == trade_id).values(step = 1)
		conn.execute(s)
		s = trades.select().where(trades.c.id == trade_id)
		trade = conn.execute(s).all()[0]
		coming_from_step_0 = True

	if trade.step == 1:
		shouldCancel, coin_record_two = tradeWaitForContract(trade_index, trade, trade_currency_two, currency_two, not trade.is_buyer, coming_from_step_0, trade_currency_one, currency_one)

		s = trades.update().where(trades.c.id == trade_id).values(step = 2)
		conn.execute(s)
		s = trades.select().where(trades.c.id == trade_id)
		trade = conn.execute(s).all()[0]

	if trade.step == 2:
		trade_threads_messages[trade_index] = "Starting last step..."
		trade_threads_addresses[trade_index] = None

		cancelTrade = shouldCancel
		if not cancelTrade:
			if trade.is_buyer:
				coin_record_two, cancelTrade = shouldCancelTrade(trade_index, trade, trade_currency_two, currency_two, coin_record_two)
			else:
				coin_record_one, cancelTrade = shouldCancelTrade(trade_index, trade, trade_currency_one, currency_one, coin_record_one)

		trade_threads_files[trade_index].write(f"Cancel trade: {cancelTrade}\n")
		trade_threads_files[trade_index].flush()
		if cancelTrade:
			solution_program = getSolutionProgram("CANCEL-" + str(random.SystemRandom().getrandbits(128))).as_bin().hex()
			if trade.is_buyer:
				tradeClaimContract(trade_index, trade, trade_currency_one, currency_one, solution_program, coin_record_one, True)
			else:
				tradeClaimContract(trade_index, trade, trade_currency_two, currency_two, solution_program, coin_record_two, True)
		else:
			if trade.is_buyer:
				solution_program = getSolutionProgram(trade.secret).as_bin().hex()
				tradeClaimContract(trade_index, trade, trade_currency_two, currency_two, solution_program, coin_record_two)
			else:
				solution_program = lookForSolutionInBlockchain(trade_index, trade, trade_currency_two, currency_two, coin_record_two, trade_currency_one, currency_one)
				if solution_program == False:
					tradeClaimContract(trade_index, trade, trade_currency_two, currency_two, solution_program, coin_record_two, True)
				else:
					tradeClaimContract(trade_index, trade, trade_currency_one, currency_one, solution_program, coin_record_one)

	conn.close()

class Trade(Resource):
	def get(self, trade_id):
		global trade_threads_ids, trade_threads_messages, trade_threads_addresses, trade_threads_files, trade_threads_commands
		if not trade_id in trade_threads_ids:
			t = threading.Thread(target=tradeCode, args=(trade_id, ))
			trade_threads_ids.append(trade_id)
			trade_threads_messages.append("Starting thread...")
			trade_threads_addresses.append(None)
			trade_threads_files.append(open(f"{trade_id}-log.txt", "a+"))
			trade_threads_commands.append(None)
			t.start()

		index = 0
		for i, v in enumerate(trade_threads_ids):
			if v == trade_id:
				index = i
		return {
			"message": trade_threads_messages[index],
			"address": trade_threads_addresses[index]
		}

	def addTradeCurrency(self, engine, data):
		conn = engine.connect()

		s = trade_currencies.select().where(trade_currencies.c.id == data['id'])
		result = conn.execute(s)
		st = None
		if len(result.all()) == 0:
			st = trade_currencies.insert()
		else:
			st = trade_currencies.update().where(trade_currencies.c.id == data['id'])
		st = st.values(
			id = data['id'],
			address_prefix = data['address_prefix'],
			fee = data['fee'],
			max_block_height = data['max_block_height'],
			min_confirmation_height = data['min_confirmation_height'],
			from_address = data['from_address'],
			to_address = data['to_address'],
			total_amount = data['total_amount']
		)
		conn.execute(st)

		conn.close()

	def put(self, trade_id):
		parser = reqparse.RequestParser()
		parser.add_argument('trade_currency_one', type=dict, required=True)
		parser.add_argument('trade_currency_two', type=dict, required=True)
		parser.add_argument('secret', type=str, required=True)
		parser.add_argument('secret_hash', type=str, required=True)
		parser.add_argument('is_buyer', type=bool, required=True)
		parser.add_argument('secret', type=str, required=True)
		parser.add_argument('step', type=int, required=True)

		args = parser.parse_args(strict=True)

		self.addTradeCurrency(engine, args['trade_currency_one'])
		self.addTradeCurrency(engine, args['trade_currency_two'])

		conn = engine.connect()

		s = trades.select().where(trades.c.id == trade_id)
		result = conn.execute(s)
		st = None
		if len(result.all()) == 0:
			st = trades.insert()
		else:
			st = trades.update().where(trades.c.id == trade_id)
		st = st.values(
			id = trade_id,
			trade_currency_one = args['trade_currency_one']['id'],
			trade_currency_two = args['trade_currency_two']['id'],
			secret_hash = args['secret_hash'],
			is_buyer = args['is_buyer'],
			secret = args['secret'],
			step = args['step'],
		)
		conn.execute(st)

		conn.close()
		return {'success': True}

	def delete(self, trade_id):
		conn = engine.connect()

		stmt = trades.delete().where(trades.c.id == trade_id)
		conn.execute(stmt)

		conn.close()
		return {'success': True}

class EthTrades(Resource):
	def get(self):
		conn = engine.connect()

		s = eth_trades.select()
		result = conn.execute(s)
		res = []

		for row in result:
			stmt = trade_currencies.select().where(trade_currencies.c.id == row[1])
			trade_currency = conn.execute(stmt).all()[0]

			res.append(ethTradesRowToJson(row, tradeCurrencyRowToJson(trade_currency)))

		conn.close()
		return {'trades': res}

eth_trade_responses = {}

def getResponse(trade_id, key, retry=True):
	global eth_trade_responses
	if eth_trade_responses.get(trade_id, -1) == -1:
		eth_trade_responses[trade_id] = {}

	val = eth_trade_responses[trade_id].get(key, -1)
	while retry and val == -1:
		time.sleep(1)
		val = eth_trade_responses[trade_id].get(key, -1)

	if val == -1:
		return False
	return val

def ethTradeCode(trade_id):
	global trade_threads_ids, trade_threads_messages, trade_threads_addresses, trade_threads_files, eth_trade_responses
	global ETH_MAX_BLOCK_HEIGHT, ETH_REQUIRED_CONFIRMATIONS
	trade_index = 0
	for i, v in enumerate(trade_threads_ids):
		if v == trade_id:
			trade_index = i

	trade_threads_files[trade_index].write("ONLY SHARE THE CONTENTS OF THIS FILE WITH TRUSTED PEOPLE\n")

	conn = engine.connect()

	s = eth_trades.select().where(eth_trades.c.id == trade_id)
	trade = conn.execute(s).all()[0]
	trade_threads_files[trade_index].write(f"Trade\n\n")
	trade_threads_files[trade_index].write(f"Trade id: {trade_id}\n")
	trade_threads_files[trade_index].write(f"Secret hash: {trade.secret_hash}\n")
	trade_threads_files[trade_index].write(f"Is Buyer?: {trade.is_buyer}\n")
	trade_threads_files[trade_index].write(f"Secret: {trade.secret}\n")
	trade_threads_files[trade_index].write(f"Step: {trade.step}\n\n\n")
	trade_threads_files[trade_index].flush()

	s = trade_currencies.select().where(trade_currencies.c.id == trade.trade_currency)
	trade_currency = conn.execute(s).all()[0]
	trade_threads_files[trade_index].write(f"Trade currency\n\n")
	_dumpTradeCurrency(trade_index, trade_currency)

	s = currencies.select().where(currencies.c.address_prefix == trade_currency.address_prefix)
	currency = conn.execute(s).all()[0]

	coin_record = False
	coming_from_step_0 = False

	shouldCancel = False

	swap_id = "None"

	swap_data = {
		"contract_address": getContractAddress(trade[9]),
		"token_address": getTokenAddress(trade[9], trade[10]),
		"secret_hash": trade[5],
		"from_address": trade[2],
		"to_address": trade[3],
		"max_block_height": ETH_MAX_BLOCK_HEIGHT,
		"amount": trade[4]
	}
	if trade.step == 0:
		trade_threads_addresses[trade_index] = None
		trade_threads_files[trade_index].write(f"Swap data: {json.dumps(swap_data)}\n\n")
		trade_threads_files[trade_index].flush()

		if trade.is_buyer:
			trade_threads_messages[trade_index] = f"Press the button below to create the swap on the Ethereum blockchain\nMake sure you're connected to the following network: {trade[9]}"
			trade_threads_commands[trade_index] = {"code": "CREATE_SWAP", "args": swap_data}

			token_approval_tx_sent = getResponse(trade_id, "token_approval_tx_sent")
			trade_threads_messages[trade_index] = "Confirming token approval..."
			trade_threads_commands[trade_index] = None
			token_approval_tx_confirmed = getResponse(trade_id, "token_approval_tx_confirmed")
			trade_threads_messages[trade_index] = "Please approve the 2nd transaction"
			created = getResponse(trade_id, "createSwap_tx_sent")
			trade_threads_messages[trade_index] = "Waiting for 2nd transaction to be confirmed..."
			created = getResponse(trade_id, "swap_created")

		trade_threads_messages[trade_index] = f"Waiting for swap to be confirmed on the Ethereum blockchain...\nMake sure you're connected to the following network: {trade[9]}"
		trade_threads_commands[trade_index] = {"code": "WAIT_FOR_SWAP", "args": swap_data}
		
		swap_id = getResponse(trade_id, "swap_id")
		confirmations = getResponse(trade_id, "confirmations")

		while confirmations < ETH_REQUIRED_CONFIRMATIONS:
			trade_threads_messages[trade_index] = f"Confirming swap creation ({confirmations}/{ETH_REQUIRED_CONFIRMATIONS})"
			confirmations = getResponse(trade_id, "confirmations")
			time.sleep(5)

		trade_threads_messages[trade_index] = f"Commencing to next step..."
		trade_threads_commands[trade_index] = None

		shouldCancel = getResponse(trade_id, "should_cancel", False)

		s = eth_trades.update().where(eth_trades.c.id == trade_id).values(step = 1)
		conn.execute(s)
		s = eth_trades.select().where(eth_trades.c.id == trade_id)
		trade = conn.execute(s).all()[0]

		coming_from_step_0 = True

	if trade.step == 1:
		shouldCancel = shouldCancel or getResponse(trade_id, "should_cancel", False)
		if not shouldCancel:
			eth_trade_responses[trade_id]['confirmations'] = -2
			trade_threads_messages[trade_index] = f"Getting ETH transaction confirmations..."
			trade_threads_commands[trade_index] = {"code": "WAIT_FOR_SWAP", "args": swap_data}
			while eth_trade_responses[trade_id]['confirmations'] == -2:
				time.sleep(1)

			trade_threads_commands[trade_index] = None

			def checkFunc():
				global eth_trade_responses
				return eth_trade_responses[trade_id]["confirmations"] < ETH_MAX_BLOCK_HEIGHT * 3 // 4
			shouldCancel, coin_record = tradeWaitForContract(trade_index, trade, trade_currency, currency, not trade.is_buyer, False, False, False, checkFunc)

		s = eth_trades.update().where(eth_trades.c.id == trade_id).values(step = 2)
		conn.execute(s)
		s = eth_trades.select().where(eth_trades.c.id == trade_id)
		trade = conn.execute(s).all()[0]

	if trade.step == 2:
		trade_threads_messages[trade_index] = "Starting last step..."
		trade_threads_addresses[trade_index] = None

		cancelTrade = shouldCancel or getResponse(trade_id, "should_cancel", False)
		if not cancelTrade:
			coin_record, cancelTrade = shouldCancelTrade(trade_index, trade, trade_currency, currency, coin_record)
			eth_trade_responses[trade_id]['confirmations'] = -2
			trade_threads_messages[trade_index] = f"Verifying ETH height..."
			trade_threads_commands[trade_index] = {"code": "WAIT_FOR_SWAP", "args": swap_data}
			while eth_trade_responses[trade_id]["confirmations"] == -2:
				time.sleep(1)

			trade_threads_commands[trade_index] = None
			cancelTrade = cancelTrade or (eth_trade_responses[trade_id]['confirmations'] > ETH_MAX_BLOCK_HEIGHT * 3 // 4)

		trade_threads_files[trade_index].write(f"Cancel trade: {cancelTrade}\n")
		trade_threads_files[trade_index].flush()
		if cancelTrade:
			cancelStr = "CANCEL-" + str(random.SystemRandom().getrandbits(128))
			if not trade.is_buyer:
				solution_program = getSolutionProgram(cancelStr).as_bin().hex()
				tradeClaimContract(trade_index, trade, trade_currency, currency, solution_program, coin_record, True)
			else:
				trade_threads_messages[trade_index] = "Cancel trade - waiting for the swap to expire..."
				trade_threads_commands[trade_index] = None
				while eth_trade_responses[trade_id]["confirmations"] < ETH_MAX_BLOCK_HEIGHT:
					trade_threads_messages[trade_index] = f"{ETH_MAX_BLOCK_HEIGHT - eth_trade_responses[trade_id]['confirmations']} blocks left before you can cancel the swap..."
					trade_threads_commands[trade_index] = {"code": "WAIT_FOR_SWAP", "args": swap_data}
				trade_threads_messages[trade_index] = "Press the button below to cancel the swap :("
				trade_threads_commands[trade_index] = {"code": "CANCEL_SWAP", "args": swap_data}
				swap_completed = getResponse(trade_id, "swap_completed")
		else:
			if not trade.is_buyer:
				trade_threads_messages[trade_index] = "Searching the Chia blockchan for a solution..."
				trade_threads_commands[trade_index] = None
				solution_program = lookForSolutionInBlockchain(trade_index, trade, trade_currency, currency, coin_record)
				secret = getSecretFromSolutionProgram(solution_program)
				trade_threads_messages[trade_index] = "Press the button below to claim your ETH"
				swap_data["secret"] = secret
				trade_threads_commands[trade_index] = {"code": "COMPLETE_SWAP", "args": swap_data}
				swap_completed = getResponse(trade_id, "swap_completed")
			else:
				trade_threads_messages[trade_index] = "Preparing to claim XCH..."
				trade_threads_commands[trade_index] = None
				solution_program = getSolutionProgram(trade.secret).as_bin().hex()
				tradeClaimContract(trade_index, trade, trade_currency, currency, solution_program, coin_record)
				
		trade_threads_messages[trade_index] = "Done :)"
		trade_threads_commands[trade_index] = None
	conn.close()

class EthTrade(Resource):
	def get(self, trade_id):
		global trade_threads_ids, etrade_threads_messages, trade_threads_addresses, trade_threads_commands, trade_threads_files
		if not trade_id in trade_threads_ids:
			t = threading.Thread(target=ethTradeCode, args=(trade_id, ))
			trade_threads_ids.append(trade_id)
			trade_threads_messages.append("Starting thread...")
			trade_threads_addresses.append(None)
			trade_threads_commands.append(None)
			trade_threads_files.append(open(f"{trade_id}-ETH-log.txt", "a+"))
			t.start()

		index = 0
		for i, v in enumerate(trade_threads_ids):
			if v == trade_id:
				index = i
		return {
			"message": trade_threads_messages[index],
			"address": trade_threads_addresses[index],
			"command": trade_threads_commands[index]
		}

	def addTradeCurrency(self, engine, data):
		conn = engine.connect()

		s = trade_currencies.select().where(trade_currencies.c.id == data['id'])
		result = conn.execute(s)
		st = None
		if len(result.all()) == 0:
			st = trade_currencies.insert()
		else:
			st = trade_currencies.update().where(trade_currencies.c.id == data['id'])
		st = st.values(
			id = data['id'],
			address_prefix = data['address_prefix'],
			fee = data['fee'],
			max_block_height = data['max_block_height'],
			min_confirmation_height = data['min_confirmation_height'],
			from_address = data['from_address'],
			to_address = data['to_address'],
			total_amount = data['total_amount']
		)
		conn.execute(st)

		conn.close()

	def post(self, trade_id):
		global eth_trade_responses
		parser = reqparse.RequestParser()
		parser.add_argument('data', type=dict, required=True)

		args = parser.parse_args(strict=True)

		if eth_trade_responses.get(trade_id, -1) == -1:
			eth_trade_responses[trade_id] = {}

		for key, value in args['data'].items():
			eth_trade_responses[trade_id][key] = value

	def put(self, trade_id):
		parser = reqparse.RequestParser()
		parser.add_argument('trade_currency', type=dict, required=True)
		parser.add_argument('eth_from_address', type=str, required=True)
		parser.add_argument('eth_to_address', type=str, required=True)
		parser.add_argument('total_gwei', type=int, required=True)
		parser.add_argument('secret', type=str, required=True)
		parser.add_argument('secret_hash', type=str, required=True)
		parser.add_argument('is_buyer', type=bool, required=True)
		parser.add_argument('secret', type=str, required=True)
		parser.add_argument('step', type=int, required=True)
		parser.add_argument('network', type=str, required=True)
		parser.add_argument('token', type=str, required=True)

		args = parser.parse_args(strict=True)

		self.addTradeCurrency(engine, args['trade_currency'])

		conn = engine.connect()

		s = eth_trades.select().where(eth_trades.c.id == trade_id)
		result = conn.execute(s)
		st = None
		if len(result.all()) == 0:
			st = eth_trades.insert()
		else:
			st = eth_trades.update().where(eth_trades.c.id == trade_id)
		st = st.values(
			id = trade_id,
			trade_currency = args['trade_currency']['id'],
			eth_from_address = args['eth_from_address'],
			eth_to_address = args['eth_to_address'],
			total_gwei = args['total_gwei'],
			secret_hash = args['secret_hash'],
			is_buyer = args['is_buyer'],
			secret = args['secret'],
			step = args['step'],
			network = args['network'],
			token = args['token']
		)
		conn.execute(st)

		conn.close()
		return {'success': True}

	def delete(self, trade_id):
		conn = engine.connect()

		stmt = eth_trades.delete().where(eth_trades.c.id == trade_id)
		conn.execute(stmt)

		conn.close()
		return {'success': True}


class EthNetworks(Resource):
	def get(self):
		return json.loads(getNetworksString())


api.add_resource(PingService, '/api/ping')
api.add_resource(ConnectionStatus, '/api/connection-status')
api.add_resource(Currencies, '/api/currencies')
api.add_resource(Trades, '/api/trades')
api.add_resource(Currency, '/api/currency/<string:address_prefix>')
api.add_resource(Trade, '/api/trade/<string:trade_id>')
api.add_resource(EthTrades, '/api/eth/trades')
api.add_resource(EthNetworks, '/api/eth/networks')
api.add_resource(EthTrade, '/api/eth/trade/<string:trade_id>')

@app.route('/', defaults={'path': 'index.html'})
@app.route('/<path:path>')
def get_resource(path):
	return send_from_directory('html', path)

if __name__ == '__main__':
	app.run(host='127.0.0.1', port=4143, debug=debug)