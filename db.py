from sqlalchemy import create_engine, MetaData, Table, Column, Integer, BigInteger, String, ForeignKey, Boolean
from config import debug
from pathlib import Path
import os

engine = create_engine('sqlite:///data.db', echo = debug)
meta = MetaData()

currencies = Table(
	'currencies', meta,
	Column('address_prefix', String, primary_key = True),
	Column('name', String),
	Column('photo_url', String),
	Column('units_per_coin', BigInteger),
	Column('min_fee', BigInteger),
	Column('default_max_block_height', Integer),
	Column('default_min_confirmation_height', Integer),
	Column('host', String),
	Column('port', Integer),
	Column('ssl_directory', String),
)

trade_currencies = Table(
	'trade_currencies', meta,
	Column('id', String, primary_key = True),
	Column('address_prefix', String, ForeignKey('currencies.address_prefix')),
	Column('fee', BigInteger),
	Column('max_block_height', Integer),
	Column('min_confirmation_height', Integer),
	Column('from_address', String),
	Column('to_address', String),
	Column('total_amount', BigInteger), # includes 2 * fee
)

trades = Table(
	'trades', meta,
	Column('id', String, primary_key = True),
	Column('trade_currency_one', String, ForeignKey('trade_currencies.id')),
	Column('trade_currency_two', String, ForeignKey('trade_currencies.id')),
	Column('secret_hash', String),
	Column('is_buyer', Boolean),
	Column('secret', String),
	Column('step', Integer),
)

meta.create_all(engine)

conn = engine.connect()


# Here's how to find the required info for a currency by using its GitHub repos
# Note: initial-config.yaml is located under {currency-name-lowercase}/util/initial-config.yaml
def addCurrency(
	address_prefix, # Search for config -> mainnet -> address_prefix in initial-config.yaml
	name, # Hopefully you don't require help for this one
	photo_url, # Go to the root of the crypto repo and click on '<CRYPTO_NAME>-gui' or 'chia-gui'. Click on the repository name again (the URL needs to look like 'https://github.com/Flax-Network/flax-blockchain-gui' - no hashes / hex data!) and then go to src -> assets -> img and choose the file that ends with '_circle.svg'. Click on 'Raw' and copy the URL.
	units_per_coin, # Return to the root of the crypto repo (not the '-gui' one!) and go to <NAME> -> consensus -> block_rewards.py. You should see a variable named _mojo_per_<NAME> (_mojo_per_flax, _mojo_per_chia - mojo might be replaced with a different name) set to a high number (usually 1000000000000). Copy that number and put it here (digits only)
	min_fee, # From my understanding, there's no minimum fee, so you can just set this to 0. However, setting the fee to 1 mojo MIGHT give the transactions higher priority and lead to better confirmation times. Keep in mind that the fee is paid two times: once when the contract is created and one time when the contract is claimed.
	default_max_block_height, # This should be set to the approximate average number of blocks added in a 24h period. Go to <NAME> -> consensus -> default_constants.py and look for the line where "EPOCH_BLOCKS" is set.
	default_min_confirmation_height, # This value is little bit subjective and depends on the stability of the network. Recommended minimum is 25.
	host, # Usually 127.0.0.1
	port, # Go to initial-config.yaml and look for 'rpc_port' under 'full_node'
	ssl_directory): # Usually %HOME%/.<NAME>/mainnet/config/ssl - just use the guessSslDirFor(currencyName) function
	s = currencies.select().where(currencies.c.address_prefix == address_prefix)
	result = conn.execute(s)
	if len(result.all()) == 0:
		ins = currencies.insert().values(
			address_prefix = address_prefix,
			name = name,
			photo_url = photo_url,
			units_per_coin = units_per_coin,
			min_fee = min_fee,
			default_max_block_height = default_max_block_height,
			default_min_confirmation_height = default_min_confirmation_height,
			host = host,
			port = port,
			ssl_directory = ssl_directory
		)
		conn.execute(ins)

def guessSslDirFor(currencyName):
	return os.path.join(str(Path.home()), f".{currencyName.lower()}/mainnet/config/ssl")


addCurrency('xch', 'Chia', 'https://raw.githubusercontent.com/Chia-Network/chia-blockchain-gui/main/src/assets/img/chia_circle.svg', 1000000000000, 1, 192, 32, '127.0.0.1', 8555, guessSslDirFor("Chia"))
addCurrency('xfx', 'Flax', 'https://raw.githubusercontent.com/Flax-Network/flax-blockchain-gui/main/src/assets/img/flax_circle.svg', 1000000000000, 1, 192, 32, '127.0.0.1', 6755, guessSslDirFor("Flax"))
addCurrency('cgn', 'Chaingreen', 'https://raw.githubusercontent.com/ChainGreenOrg/chaingreen-blockchain-gui/main/src/assets/img/chia_circle.svg', 1000000000000, 1, 192, 32, '127.0.0.1', 8855, guessSslDirFor("Chaingreen"))
addCurrency('xcc', 'Chives', 'https://raw.githubusercontent.com/HiveProject2021/chives-blockchain-gui/main/src/assets/img/chives_circle.png', 100000000, 1, 192, 32, '127.0.0.1', 9755, guessSslDirFor("Chives"))
addCurrency('spare', 'Spare', 'https://raw.githubusercontent.com/Spare-Network/spare-blockchain/master/spare-blockchain-gui/src/assets/img/spare.ico', 1000000000000, 1, 192, 32, '127.0.0.1', 9555, guessSslDirFor("spare-blockchain"))
addCurrency('xfl', 'Flora', 'https://raw.githubusercontent.com/Flora-Network/flora-blockchain-gui/main/src/assets/img/flora_circle.png', 1000000000000, 1, 192, 32, '127.0.0.1', 18755, guessSslDirFor("Flora"))
addCurrency('xdg', 'DogeChia', 'https://raw.githubusercontent.com/DogeChia/dogechia-blockchain-gui/main/src/assets/img/dogechia.png', 1000000000000, 1, 192, 32, '127.0.0.1', 6769, guessSslDirFor("DogeChia"))
# no seno_circle.svg, no logo.
addCurrency('xse', 'Seno', 'https://raw.githubusercontent.com/Chia-Network/chia-blockchain-gui/main/src/assets/img/chia_circle.svg', 1000000000000, 1, 192, 32, '127.0.0.1', 18555, guessSslDirFor("Seno2"))
addCurrency('xcr', 'Chiarose', 'https://raw.githubusercontent.com/snight1983/chia-rosechain/main/chia-rosechain-gui/src/assets/img/chia_circle.png', 1000000000, 1, 192, 32, '127.0.0.1', 8025, guessSslDirFor("Chiarose"))
addCurrency('hdd', 'HDDCoin', 'https://raw.githubusercontent.com/HDDcoin-Network/hddcoin-blockchain/main/hddcoin-blockchain-gui/src/assets/img/hddcoin_circle.svg', 1000000000000, 1, 192, 32, '127.0.0.1', 28555, guessSslDirFor("HDDCoin"))
addCurrency('sit', 'Silicoin', 'https://raw.githubusercontent.com/silicoin-network/silicoin-blockchain-gui/main/src/assets/img/chia_circle.png', 1000000000000, 1, 192, 32, '127.0.0.1', 10555, guessSslDirFor("Silicoin"))
addCurrency('gdog', 'GreenDoge', 'https://raw.githubusercontent.com/GreenDoge-Network/greendoge-blockchain/main/greendoge-blockchain-gui/src/assets/img/greendoge_circle.png', 1000000000000, 1, 192, 32, '127.0.0.1', 6655, guessSslDirFor("GreenDoge"))
addCurrency('avo', 'Avocado', 'https://raw.githubusercontent.com/Avocado-Network/avocado-blockchain-gui/main/src/assets/img/avocado_circle.png', 1000000000000, 1, 192, 32, '127.0.0.1', 7544, guessSslDirFor("Avocado"))
addCurrency('xka', 'Kale', 'https://raw.githubusercontent.com/Kale-Network/kale-blockchain/main/kale-blockchain-gui/src/assets/img/kale_circle.svg', 1000000000000, 1, 192, 32, '127.0.0.1', 6355, guessSslDirFor("Kale"))
addCurrency('xtx', 'Taco', 'https://raw.githubusercontent.com/Taco-Network/taco-blockchain/main/taco-blockchain-gui/src/assets/img/taco_circle.svg', 1000000000000, 1, 192, 32, '127.0.0.1', 18735, guessSslDirFor("Taco"))
addCurrency('xeq', 'Equality', 'https://raw.githubusercontent.com/Equality-Network/equality-blockchain-gui/master/src/assets/img/equality_circle.png', 1000000000000, 1, 192, 32, '127.0.0.1', 9547, guessSslDirFor("Equality"))
addCurrency('sock', 'Socks', 'https://bitbucket.org/Socks-Network/socks-blockchain-gui/raw/aefb284f40a2ff521591d79702b478317581ce94/src/assets/img/socks_circle.svg', 1000000000000, 1, 192, 32, '127.0.0.1', 58455, guessSslDirFor("Socks"))
addCurrency('wheat', 'Wheat', 'https://raw.githubusercontent.com/wheatnetwork/wheat-blockchain-gui/main/src/assets/img/wheat_circle.svg', 1000000000000, 1, 192, 32, '127.0.0.1', 21555, guessSslDirFor("Wheat"))
addCurrency('xmx', 'Melati', 'https://raw.githubusercontent.com/Melati-Network/melati-blockchain-gui/main/src/assets/img/melati_circle.svg', 1000000000000, 1, 192, 32, '127.0.0.1', 2555, guessSslDirFor("Melati"))
addCurrency('tad', 'Tad', 'https://raw.githubusercontent.com/Tad-Network/tad-blockchain-gui/main/src/assets/img/tad_circle.png', 1000000000000, 1, 192, 32, '127.0.0.1', 4555, guessSslDirFor("Tad"))
addCurrency('xsc', 'Sector', 'https://raw.githubusercontent.com/Sector-Network/sector-blockchain-gui/main/src/assets/img/sector_circle.svg', 1000000000000, 1, 192, 32, '127.0.0.1', 5555, guessSslDirFor("Sector"))
addCurrency('cac', 'Cactus', 'https://raw.githubusercontent.com/Cactus-Network/cactus-blockchain/main/cactus-blockchain-gui/src/assets/img/cactus_circle.svg', 1000000000000, 1, 192, 32, '127.0.0.1', 11555, guessSslDirFor("Cactus"))
addCurrency('cans', 'Cannabis', 'https://raw.githubusercontent.com/CannabisChain/cannabis-blockchain-gui/main/src/assets/img/cannabis_circle.png', 1000000000000, 1, 192, 32, '127.0.0.1', 5540, guessSslDirFor("Cannabis"))
addCurrency('xmz', 'Maize', 'https://raw.githubusercontent.com/Maize-Network/maize-blockchain/main/maize-blockchain-gui/src/assets/img/chia_circle.svg', 1000000000000, 1, 192, 32, '127.0.0.1', 8655, guessSslDirFor("Maize"))

conn.close()