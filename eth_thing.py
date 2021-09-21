import json

ETH_MAX_BLOCK_HEIGHT = 256
ETH_REQUIRED_CONFIRMATIONS = 7 # TODO: change back to 40 before releasing on mainnet!
def getNetworksString():
	return open("networks.json", "r").read()

networks = json.loads(getNetworksString())["networks"]

def getContractAddress(network):
	return networks[network]["address"]

def getTokenAddress(network, token):
	return networks[network]["token_addresses"][token]