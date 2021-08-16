import requests
import urllib3
import os
from helper import bytes32
import time
from config import debug

urllib3.disable_warnings()

class FullNodeClient():
	def __init__(self, ssl_directory, host, port, logfile=None):
		self.cert_path = os.path.join(ssl_directory, 'full_node/private_full_node.crt')
		self.key_path = os.path.join(ssl_directory, 'full_node/private_full_node.key')
		self.host = host
		self.port = port
		self.API_url = f"https://{host}:{port}"
		self.logfile = logfile

	def _makeRequest(self, endpoint, data):
		url = f"{self.API_url}{endpoint}"
		if debug:
			print(url)
		if self.logfile is not None:
			self.logfile.write(f"Request to {endpoint}, data: {data}\n")
			self.logfile.flush()
		try:
			r = requests.post(url, json=data, cert=(self.cert_path, self.key_path), verify=False)
			if debug:
				print(endpoint, data, r.text)
			if self.logfile is not None:
				self.logfile.write(f"Request to {endpoint}, data: {data}, response: {r.text}\n")
				self.logfile.flush()
			return r.json()
		except:
			return {}

	def getBlockchainState(self):
		return self._makeRequest("/get_blockchain_state", {})

	def getBlockchainHeight(self):
		r = self._makeRequest("/get_blockchain_state", {})
		while r == {} or r['blockchain_state']['sync']['synced'] == False:
			time.sleep(20)
			r = self._makeRequest("/get_blockchain_state", {})
		h = r['blockchain_state']['peak']['height']
		if h == 0:
			return self.getBlockchainHeight()
		return h

	def getContractCoinRecord(self, puzzleHash, start, include_spent_coins = False):
		if debug:
			print(f"Searching for puzzle hash: {puzzleHash}")
		result = self._makeRequest("/get_coin_records_by_puzzle_hash", {
			"include_spent_coins": include_spent_coins,
			"puzzle_hash": puzzleHash,
			"start": start,
		})
		if result == {} or len(result['coin_records']) == 0:
			return False
		coin_record = result['coin_records'][0]
		return coin_record

	def pushTransaction(self, puzzle, solution, coin):
		resp = self._makeRequest("/push_tx", {
			"spend_bundle": {
				"coin_solutions": [{
					"coin": coin,
					"puzzle_reveal": puzzle,
					"solution": solution,
				}],
				"aggregated_signature": "0xc00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000", 
			}
		})
		if resp == {} or not resp["success"]:
			return False
		if resp["status"] == "SUCCESS":
			return True
		return "pending"
		

	def getCoinSolution(self, coinId, height):
		resp = self._makeRequest("/get_puzzle_and_solution", {
				"coin_id": coinId,
				"height": height,
			})
		if resp == {} or resp.get("coin_solution", -1) == -1:
			return False
		return resp["coin_solution"]["solution"]