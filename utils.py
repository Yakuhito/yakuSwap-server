def currencyRowToJson(row):
	# ('xfx', 'Flax', 'https://flaxnetwork.org/logo.svg', 1000000000, 1, 5000, 10, '127.0.0.1', 8444, 'dir')
	return {
		'address_prefix': row[0],
		'name': row[1],
		'photo_url': row[2],
		'units_per_coin': row[3],
		'min_fee': row[4],
		'default_max_block_height': row[5],
		'default_min_confirmation_height': row[6],
		'host': row[7],
		'port': row[8],
		'ssl_directory': row[9]
	}


def tradeCurrencyRowToJson(row):
	return {
		'id': row['id'],
		'address_prefix': row['address_prefix'],
		'fee': row['fee'],
		'max_block_height': row['max_block_height'],
		'min_confirmation_height':row['min_confirmation_height'],
		'from_address': row['from_address'],
		'to_address': row['to_address'],
		'total_amount': row['total_amount']
	}



def tradesRowToJson(row, tradeCurrencyOneRow, tradeCurrencyTwoRow):
	return {
		'id': row[0],
		'trade_currency_one': tradeCurrencyOneRow, # tradeCurrencyRowToJson(tradeCurrencyOneRow), # row[1]
		'trade_currency_two': tradeCurrencyTwoRow, # tradeCurrencyRowToJson(tradeCurrencyTwoRow), # row[2]
		'secret_hash': row[3],
		'is_buyer': row[4],
		'secret': row[5],
		'step': row[6]
	}

def ethTradesRowToJson(row, tradeCurrency):
	return {
		'id': row[0],
		'trade_currency': tradeCurrencyRowToJson(tradeCurrency), # row[1]
		'eth_from_address': row[2],
		'eth_to_address': row[3],
		'total_gwei': row[4],
		'secret_hash': row[5],
		'is_buyer': row[6],
		'secret': row[7],
		'step': row[8],
		'network': row[9],
		'token': row[10]
	}