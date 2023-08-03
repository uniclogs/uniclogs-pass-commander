import logging
from systemd.journal import JournalHandler

def set_log():
	log = logging.getLogger('pass_commander')
	log.setLevel(logging.DEBUG)
	log.addHandler(JournalHandler())

	'''
	# Can also log to a file
	handler = logging.FileHandler('pass_commander.log')
	handler.setLevel(logging.DEBUG)
	# Create the formatter and set
	formatter = logging.Formatter(
		"%(asctime)s - %(levelname)s - %(messages)s",
		datefmt = "%d-%m-%Y %H:%M:%S",
	)
	handler.setFormatter(formatter)
	# Add file handler to logger
	log.addHandler(handler)
	'''

	return log
