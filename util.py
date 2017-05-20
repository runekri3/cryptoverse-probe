import os
import hashlib
import binascii
import time
import math
import numpy
import uuid
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key

def difficultyFudge():
	return int(os.getenv('DIFFICULTY_FUDGE', '0'))
def difficultyInterval():
	return int(os.getenv('DIFFICULTY_INTERVAL', '7560'))
def difficultyDuration():
	return int(os.getenv('DIFFICULTY_DURATION', '1209600'))
def difficultyStart():
	return int(os.getenv('DIFFICULTY_START', '486604799'))
def shipReward():
	return int(os.getenv('SHIP_REWARD', '10'))
def maximumStarLogSize():
	return int(os.getenv('STARLOGS_MAX_BYTES', '999999'))
def maximumEventSize():
	return int(os.getenv('EVENTS_MAX_BYTES', '999999'))
def cartesianDigits():
	return int(os.getenv('CARTESIAN_DIGITS', '3'))
def jumpCostMinimum():
	return float(os.getenv('JUMP_COST_MIN', '0.01'))
def jumpCostMaximum():
	return float(os.getenv('JUMP_COST_MAX', '1.0'))
def jumpDistanceMaximum():
	return float(os.getenv('JUMP_DIST_MAX', '256.0'))

maximumNonce = 2147483647
maximumTarget = '00000000ffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
emptyTarget = '0000000000000000000000000000000000000000000000000000000000000000'

eventTypes = [
	'unknown',
	'reward',
	'jump',
	'attack'
]

shipEventTypes = [
	'reward',
	'jump',
	'attack'
]

if not 0 <= difficultyFudge() <= 8:
	raise Exception('DIFFICULTY_FUDGE must be a value from 0 to 8 (inclusive)')
elif 0 < difficultyFudge():
	prefix = maximumTarget[difficultyFudge():]
	suffix = maximumTarget[:difficultyFudge()]
	maximumTarget = prefix + suffix

if not 3 <= cartesianDigits() <= 21:
	raise Exception('CARTESIAN_DIGITS must be a value from 3 to 21 (inclusive)')

if not 0 <= jumpCostMinimum() < 1:
	raise Exception('JUMP_COST_MIN must be a value from 0.0 to 1.0 (inclusive - exclusive)')

if not 0 < jumpCostMaximum() <= 1:
	raise Exception('JUMP_COST_MAX must be a value from 0.0 to 1.0 (exclusive - inclusive)')

if jumpCostMaximum() <= jumpCostMinimum():
	raise Exception('JUMP_COST_MIN must be less than JUMP_COST_MAX')

if jumpDistanceMaximum() <= 0:
	raise Exception('JUMP_DIST_MAX must be greater than 0.0')

def isGenesisStarLog(sha):
	'''Checks if the provided hash could only belong to the parent of the genesis star log.

	Args:
		sha (str): Hash to check.

	Results:
		bool: True if equal to the hash of the parent of the genesis block's parent.
	'''
	return sha == emptyTarget

def sha256(message):
	'''Sha256 hash of message.
	
	Args:
		message (str): Message to hash.
	
	Returns:
		str: Sha256 hash of the provided string, or the hash of nothing if None is passed.
	'''
	return hashlib.sha256('' if message is None else message).hexdigest()

def difficultyToHex(difficulty):
	'''Converts a packed int representation of difficulty to its packed hex format.
	
	Args:
		difficulty (int): Packed int format of difficulty.
	
	Returns:
		str: Packed hex format of difficulty, stripped of its leading 0x.
	'''
	return hex(difficulty)[2:]

def difficultyFromHex(difficulty):
	'''Takes a hex string of difficulty, missing the 0x, and returns the integer from of difficulty.
	
	Args:
		difficulty (str): Packed hex format of difficulty.
	
	Returns:
		int: Packed int format of difficulty.
	'''
	return int(difficulty, 16)

def difficultyFromTarget(target):
	'''Calculates the difficulty this target is equal to.
	
	Args:
		target (str): Hex target, stripped of its leading 0x.
	
	Returns:
		str: Packed hex difficulty of the target, stripped of its leading 0x.
	'''
	# TODO: Cleanup shitwise operators that use string transformations, they're ugly... though they do work...
	stripped = target.lstrip('0')

	# If we stripped too many zeros, add one back.
	if len(stripped) % 2 == 0:
		stripped = '0' + stripped
	
	count = len(stripped) / 2
	stripped = stripped[:6]
	
	# If we're past the max value allowed for the mantissa, truncate it further and increase the exponent.
	if 0x7fffff < int(stripped, 16):
		stripped = '00' + stripped[0:4]
		count += 1

	result = hex(count)[2:] + stripped

	# Negative number switcharoo
	if 0x00800000 & int(result, 16):
		result = hex(count + 1)[2:] + '00' + stripped[:4]
	# # Lazy max number check...
	# if 0x1d00ffff < int(result, 16):
	# 	result = '1d00ffff'
	return result
	

def isDifficultyChanging(height):
	'''Checks if it's time to recalculate difficulty.
	
	Args:
		height (int): Height of an entry in the chain.
	
	Returns:
		bool: True if a difficulty recalculation should take place.
	'''
	return (height % difficultyInterval()) == 0

def calculateDifficulty(difficulty, duration):
	'''Takes the packed integer difficulty and the duration of the last interval to calculate the new difficulty.
	
	Args:
		difficulty (int): Packed int format of the last difficulty.
		duration (int): Seconds elapsed since the last time difficulty was calculated.
	
	Returns:
		int: Packed int format of the next difficulty.
	'''
	if duration < difficultyDuration() / 4:
		duration = difficultyDuration() / 4
	elif duration > difficultyDuration() * 4:
		duration = difficultyDuration() * 4

	limit = long(maximumTarget, 16)
	result = long(unpackBits(difficulty), 16)
	result *= duration
	result /= difficultyDuration()

	if limit < result:
		result = limit
	
	return difficultyFromHex(difficultyFromTarget(hex(result)[2:]))

def concatStarLogHeader(starLog, includeNonce=True):
	'''Concats the header information from the provided json.
	
	Args:
		starLog (dict): StarLog to create header from.

	Returns:
		str: Resulting header.
	'''
	return '%s%s%s%s%s%s' % (starLog['version'], starLog['previous_hash'], starLog['difficulty'], starLog['events_hash'], starLog['time'], starLog['nonce'] if includeNonce else '')

def concatEvent(eventJson):
	'''Concats the information of an event from the provided json.

	Args:
		eventJson (dict): Event to pull the information from.

	Returns:
		str: Resulting concatenated information of the event.
	'''
	concat = '%s%s%s' % (eventJson['fleet_hash'], eventJson['fleet_key'], eventJson['type'])
	if eventJson['inputs']:
		for currentInput in sorted(eventJson['inputs'], key=lambda x: x['index']):
			concat += currentInput['key']
	if eventJson['outputs']:
		for currentOutput in sorted(eventJson['outputs'], key=lambda x: x['index']):
			concat += '%s%s%s%s%s' % (currentOutput['type'], currentOutput['fleet_hash'], currentOutput['key'], currentOutput['star_system'], currentOutput['count'])
	return concat

def expandRsaPublicKey(shrunkPublicKey):
	'''Reformats a shrunk Rsa public key.

	Args:
		shrunkPublicKey (str): Rsa public key without the BEGIN or END sections.
	
	Returns:
		str: The public key with its BEGIN and END sections reattatched.
	'''
	return '-----BEGIN PUBLIC KEY-----\n%s\n-----END PUBLIC KEY-----'%(shrunkPublicKey)

def rsaSign(privateKey, message):
	'''Signs a message with the provided Rsa private key.

	Args:
		privateKey (str): Rsa private key with BEGIN and END sections.
		message (str): Message to be hashed and signed.
	
	Returns:
		str: Hex signature of the message, with its leading 0x stripped.
	'''
	privateRsa = load_pem_private_key(bytes(privateKey), password=None,backend=default_backend())
	hashed = sha256(message)
	signature = privateRsa.sign(
		hashed, 
		padding.PSS(
			mgf=padding.MGF1(hashes.SHA256()),
			salt_length=padding.PSS.MAX_LENGTH
		),
		hashes.SHA256()
	)
	return binascii.hexlify(bytearray(signature))

def hashStarLog(starLog):
	'''Hashed value of the provided star log's header.

	Args:
		starLog (dict): Json data for the star log to be hashed.
	
	Returns:
		str: Supplied star log with its `events_hash`, `log_header`, and `hash` fields calculated.
	'''
	starLog['events_hash'] = hashEvents(starLog['events'])
	starLog['log_header'] = concatStarLogHeader(starLog)
	starLog['hash'] = sha256(starLog['log_header'])
	return starLog

def hashEvents(events):
	'''Hashed value of the provided events.

	Args:
		events (dict): Json data for the events to be hashed.

	Returns:
		str: Sha256 hash of the provided events.
	'''
	concat = ''
	for event in events:
		concat += hashEvent(event)
	return sha256(concat)

def hashEvent(event):
	'''Hashed value of the provided event.

	Args:
		event (dict): Json data for the event to be hashed.

	Returns:
		str: Sha256 hash of the provided event.
	'''
	return sha256(concatEvent(event))

def unpackBits(difficulty, strip=False):
	'''Unpacks int difficulty into a target hex.

	Args:
		difficulty (int): Packed int representation of a difficulty.
	
	Returns:
		str: Hex value of a target hash equal to this difficulty, stripped of its leading 0x.
	'''
	if not isinstance(difficulty, (int, long)):
		raise TypeError('difficulty is not int')
	sha = difficultyToHex(difficulty)
	digitCount = int(sha[:2], 16)

	if digitCount == 0:
		digitCount = 3

	digits = []
	if digitCount == 29:
		digits = [ sha[4:6], sha[6:8] ]
	else:
		digits = [ sha[2:4], sha[4:6], sha[6:8] ]

	digitCount = min(digitCount, 28)
	significantCount = len(digits)

	leadingPadding = 28 - digitCount
	trailingPadding = 28 - (leadingPadding + significantCount)

	base256 = ''

	for i in range(0, leadingPadding + 4):
		base256 += '00'
	for i in range(0, significantCount):
		base256 += digits[i]
	for i in range(0, trailingPadding):
		base256 += '00'
	
	if 0 < difficultyFudge():
		base256 = base256[difficultyFudge():] + base256[:difficultyFudge()]
	return base256.rstrip('0') if strip else base256

def getFleets(eventsJson):
	'''Gets all fleets with their keys.

	Args:
		eventsJson (dict): List of all events to check.
	
	Returns:
		list: A list of tuples with fleet hashes and their key.
	'''
	results = []
	for currentEvent in eventsJson:
		fleetHash = currentEvent['fleet_hash']
		fleetKey = currentEvent['fleet_key']
		if None in (fleetHash, fleetKey):
			continue
		results.append((fleetHash, fleetKey))
	return results

def getEventInputs(eventsJson):
	'''Gets all input events.

	Args:
		eventsJson (dict): List of all events to search.
	
	Returns:
		list: A list the input events.
	'''
	results = []
	for currentEvent in eventsJson:
		for currentOutput in currentEvent['inputs']:
			results.append(currentOutput)
	return results

def getEventOutputs(eventsJson):
	'''Gets all output events.

	Args:
		eventsJson (dict): List of all events to search.
	
	Returns:
		list: A list the output events.
	'''
	results = []
	for currentEvent in eventsJson:
		for currentOutput in currentEvent['outputs']:
			results.append(currentOutput)
	return results

def getEventTypeId(eventName):
	'''Gets the integer associated with the event type.

	Args:
		eventName (str): Name of the event.
	
	Returns:
		int: Integer of the event type.
	'''
	for i in range(0, len(eventTypes)):
		if eventTypes[i] == eventName:
			return i
	return 0

def getEventTypeName(eventId):
	'''Gets the str name associated with the event type.

	Args:
		eventId (int): Id of the event.
	
	Returns:
		str: Str of the event type.
	'''
	return eventTypes[eventId] if eventId is not None and eventId < len(eventTypes) else eventTypes[0]

def getJumpCost(originHash, destinationHash, count=None):
	'''Gets the floating point scalar for the number of ships that will be lost in this jump.

	Args:
		originHash (str): The starting hash of the jump.
		destinationHash (str): The ending hash of the jump.
		count (int): The number of ships in the jump.
	
	Returns:
		float: A scalar value of the ships lost in the jump.
	'''
	distance = getDistance(originHash, destinationHash)
	maxDistance = jumpDistanceMaximum()
	costMax = jumpCostMaximum()
	if maxDistance <= distance:
		return costMax if count is None else int(math.ceil(costMax * count))
	# Scalar is x^2
	scalar = math.sqrt(distance / maxDistance)
	costMin = jumpCostMinimum()
	costRange = 1.0 - ((1.0 - costMax) + costMin)
	scalar = costMin + (costRange * scalar)
	return scalar if count is None else int(math.ceil(scalar * count))

def getCartesianMinimum():
	'''Gets the (x, y, z) position of the minimum possible system.
	
	Returns:
		array: A list containing the (x, y, z) position.
	'''
	return numpy.array([0, 0, 0])

def getCartesianMaximum():
	'''Gets the (x, y, z) position of the maximum possible system.
	
	Returns:
		array: A list containing the (x, y, z) position.
	'''
	maxValue = pow(16, cartesianDigits())
	return numpy.array([maxValue, maxValue, maxValue])

def getCartesian(systemHash):
	'''Gets the (x, y, z) position of the specified system.

	Args:
		systemHash (str): The system's Sha256 hash.
	
	Returns:
		array: A list containing the (x, y, z) position.
	'''
	cartesianHash = sha256('%s%s' % ('cartesian', systemHash))
	digits = cartesianDigits()
	totalDigits = digits * 3
	cartesian = cartesianHash[-totalDigits:]
	return numpy.array([int(cartesian[:digits], 16), int(cartesian[digits:-digits], 16), int(cartesian[(2*digits):], 16)])

def getDistance(originHash, destinationHash):
	'''Gets the distance between the specified systems in cartesian space.

	Args:
		originHash (str): The origin system's Sha256 hash.
		destinationHash (str): The destination system's Sha256 hash.
	
	Returns:
		float: The distance between the two systems.
	'''
	originPos = getCartesian(originHash)
	destinationPos = getCartesian(destinationHash)
	return int(math.ceil(numpy.linalg.norm(originPos - destinationPos)))

def getUniqueKey():
	'''The sha256 of a unique id.

	Returns:
		str: The sha256 of a unique id.
	'''
	return sha256(str(uuid.uuid4()))

def getTime():
	'''UTC time in seconds.

	Returns:
		int: The number of seconds since the UTC epoch started.
	'''
	return int(time.time())