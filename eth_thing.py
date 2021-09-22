import json

ETH_MAX_BLOCK_HEIGHT = 256
ETH_REQUIRED_CONFIRMATIONS = 7 # TODO: change back to 40 before releasing on mainnet!
def getNetworksString():
	return open("networks.json", "r").read()

networks = json.loads(getNetworksString())["networks"]

def _getNetwork(networkName):
	for n in networks:
		if n["name"] == networkName:
			return n
	return networks[0]

def getContractAddress(network):
	return _getNetwork(network)["address"]

def getTokenAddress(network, token):
	return _getNetwork(network)["token_addresses"][token]