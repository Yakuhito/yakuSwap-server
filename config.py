try:
	debug = open(".debug", "r").read().strip().lower() == "true"
except:
	debug = False