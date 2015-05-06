# Copyright Menno Nijboer, 2015

from __future__ import division

import pyglet
from pyglet.gl import *

import xml.dom.minidom
import sys
import time
import datetime
import random
import math
from math import sqrt, pow

# global variables
updateFreq = 1.0/70.0
placeClickArea = 22
appFont = 'Helvetica'

# stuff to make things easier
placeClickAreaSqr = placeClickArea*placeClickArea
# modes
INTRO = 0
TRIAL = 1
DRILL = 2
CALIB = 3
END = 4

WRONG = 0
CORRECT = 1

FLASHCARD = 0
SPACING = 1

HINT = 1
NOHINT = 0

# Some global functions

# load an image from a file and center it's placement anchors
def loadAndCenterImg(imgName):
	img =  pyglet.image.load(imgName)
	img.anchor_x = img.width // 2
	img.anchor_y = img.height // 2
	return img

# create a sprite from a loaded image
def createSprite(img, x=0, y=0, visible=False):
	sprite = pyglet.sprite.Sprite(img, x=x, y=y)
	sprite.visible = visible
	return sprite	

class Teacher(object):
    # The spacing / hint cards algorithms, implemented by Jelle Dalenberg

	def __init__(self, mapPlaces, width, height, spacing, expLen, subject):
		self.width = width
		self.height = height
		self.mapPlaces = mapPlaces
		self.numPlaces = len(self.mapPlaces)
		
		self.subjectName = subject
		self.spacingFirst = spacing
		self.experimentLen = expLen
		
		# randomly locate the places
		# spacing: 0 .. 15 with 0..7 giving optional hits and 8..15 not giving hints
		# flascard: 16..31 with 16..23 not giving hits, and 24..31 giving hits. Flashcard batches are 4 places
		random.shuffle(mapPlaces)
		self.currentTrialPlace = 0
		self.calibPlaces = []
		self.calibCounter = -1
		self.maxCalib = 5
		self.trialType = DRILL
		self.trialCondition = FLASHCARD
		self.completedTrials = []
		self.scoreHistory = []
####################################################################################
		self.placeCount = 0     #counter needed for counting the self.mapPlaces
		self.lastPlace = 0  	#Last shown place
####################################################################################
		self.doSpacingTrial = True
		
		self.date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
		self.initCalibrationPlaces()
		self.completedCalibTrials = []

		# Vars for the flashcard approach
		self.flashcardResults = [WRONG,WRONG,WRONG,WRONG]
		self.flashcardBatch = 0
		self.flashcardBatchOffset = 3 # to make sure that this var becomes 0 before the first trial
		
		self.estimatedAvgSpeed = 0
		
##########################################################################
		self.treshold = -0.5          #Activation treshold
		self.F = 1                   #F in the latency equation
		self.std_a = 0.25            #Alpha in the decay equation
		self.curAct = 0              #The activity of the current
		self.trialStart = 0          #Starting time of whole session
		self.c = 0.25				 #constant c
###########################################################################
	
	def initCalibrationPlaces(self):
		# generate some random places, but well distributed
		numCalib = 0
		while numCalib < self.maxCalib:
			x = random.randrange(100, self.width-100)
			y = random.randrange(100, self.height-100)
			accepted = True
			for cp in self.calibPlaces:
				if cp.distanceTo(x, y) < 50: # we don't want places too close to eachother
					accepted = False
			if accepted:
				self.calibPlaces.append(Place(x, y))
				numCalib += 1
		
	# get the next place according to either spacing / cuecards
	def getNextTrial(self, time):
		doSpacing = False
		if self.spacingFirst:
			if time < 0.5*self.experimentLen: #first half, do spacing
				doSpacing = True
		else: #start with flashcard
			if time > 0.5*self.experimentLen: #second half, switch to spacing
				doSpacing = True
		
		if doSpacing:
			#print 'spacing trial'
			(place, type) = self.getNextSpacingPlace() 		 
			self.trialType = type                                              		
			self.currentTrialPlace = place                                     		
			self.trialCondition = SPACING											

		else: #Flashcard
			#print 'flashcard trial'
			(place, type) = self.getNextFlashcardPlace()
			self.trialType = type
			self.currentTrialPlace = place
			self.trialCondition = FLASHCARD		
		
		self.doSpacingTrial = not self.doSpacingTrial
		return (self.currentTrialPlace, self.trialType, (place < 8 or place > 23))  #determine whether a hint can appear


################################################# Spacing###########################
	
	def fixTime(self):
		(x, y) = self.mapPlaces[self.completedTrials[-2].placeIndex].coords()
		ft = self.mapPlaces[self.completedTrials[-1].placeIndex].distanceTo(x, y)
		time = ft / self.estimatedAvgSpeed
		
		#print 'ft =', time
		return time
	
    #Update alpha: Latency = F * math.exp(-act) + fixed time -> act = -math.log(latency - fixed time)/F
	def alpha(self, i, latency): #i = last shown item; latency = response time
		#print 'alpha gebuikte plaats', i
		if len(self.mapPlaces[i].times) < 3:
				self.mapPlaces[i].alpha.append(self.std_a)
				return self.std_a
		else:  	#Estimate current activation with the last decay value
			curTime = time.clock()
			old_act = self.mapPlaces[i].act
			#print old_act, 'prev act'
		  
			est_act = 0
			for j in range(len(self.mapPlaces[i].decays)):
				est_act += math.pow((curTime - self.mapPlaces[i].times[j]), -(self.mapPlaces[i].decays[j]))
			est_act = math.log(est_act)
			#print est_act, 'estimated act'
		  
			#The expected latency:
			Lexpected = self.F * math.exp(-est_act) + self.fixTime()
			#print Lexpected, 'expected'

			#The observed latency:
			Lobserved = latency
			#print Lobserved, 'observed'

			#Update Alpha
			if Lobserved - Lexpected > 0:
				a = self.mapPlaces[i].alpha[-1] + max(0.01,((Lobserved-Lexpected)/1000))
				self.mapPlaces[i].alpha.append(a)
				#print 'a increased to:', a, self.mapPlaces[i].name
				return a
			if Lobserved - Lexpected < 0:
				a = self.mapPlaces[i].alpha[-1] + min(-0.01,((Lobserved-Lexpected)/1000))
				self.mapPlaces[i].alpha.append(a)
				#print 'a decreased to:', a, self.mapPlaces[i].name
				return a

	def decay(self, i, latency):
		if self.mapPlaces[i].act == 0:
			d = self.c + self.alpha(i, latency)
			self.mapPlaces[i].decays.append(d)
		else:
			d = self.c * math.exp(self.mapPlaces[i].act) + self.alpha(i, latency)
			self.mapPlaces[i].decays.append(d)

	def activation(self, place):
		curTime = time.clock()
		if place == 0:
			act = 0
			for j in range(len(self.mapPlaces[0].times)):
				act += math.pow((curTime - self.mapPlaces[0].times[j]), -(self.mapPlaces[0].decays[j]))
			self.mapPlaces[0].act = math.log(act)
		else:
			for i in range(len(self.mapPlaces[0:place])):
				act = 0
				for j in range(len(self.mapPlaces[i].times)):
					act += math.pow((curTime - self.mapPlaces[i].times[j]), -(self.mapPlaces[i].decays[j]))
				self.mapPlaces[i].act = math.log(act)

	def memoryUpdate(self, place):
		#Add one to the number of total shows of current item
		self.mapPlaces[place].addShow()         

	def rehearse(self, place, actmin, latency):
		self.mapPlaces[actmin].times.append(time.clock())
		#Calculate the decay (and alpha) up to the last shown item
		self.memoryUpdate(actmin)
		#print self.mapPlaces[actmin].name, 'is rehearsed'
		self.lastPlace = actmin
		return actmin, TRIAL

	def getNextSpacingPlace(self):	
		#print '-----------------------------'
		#Spacing: 3 conditions; 1) first encounter, 2)rehearse or add new, 3) rehearse if all are shown
		if self.placeCount == 0:
			#Present first place  
			self.mapPlaces[self.placeCount].times.append(time.clock())
			#print self.mapPlaces[self.placeCount].name, 'is presented'
			self.memoryUpdate(self.placeCount)
			self.lastPlace = self.placeCount
			self.placeCount += 1
			return 0, DRILL
		
		if self.scoreHistory[-1] == 0:
			latency = 15
		else:
			latency = self.completedTrials[-1].RT
		
		#Calculate the decay (and alpha) up to the last shown item
		self.decay(self.lastPlace, latency)
		#Calculate activations up to the last shown item
		self.activation(self.placeCount)

		if self.placeCount < 16: #15 places for spacing
			if self.placeCount == 1:
				actmin = 0
			else: #Present new item or rehearse?: Search for lowest act
				acts = [p.act for p in self.mapPlaces[0:self.placeCount]]
				actmin = acts.index(min(acts))
				#if lowest act is below treshold: rehearse item
			if self.mapPlaces[actmin].act < self.treshold:                               
				return self.rehearse(self.placeCount, actmin, latency)
			else:
				#if lowest act is not below treshold: present new item
				self.mapPlaces[self.placeCount].times.append(time.clock())
				#print self.mapPlaces[self.placeCount].name, self.placeCount, 'is presented'
				#Calculate the decay (and alpha) up to the last shown item
				self.memoryUpdate(self.placeCount)
				lastPlace = self.placeCount
				self.lastPlace = self.placeCount
				self.placeCount += 1
				return self.lastPlace, DRILL
		else: #When all items are presented: keep rehearsing the lowest untill the session time exceeded.
			acts = [p.act for p in self.mapPlaces[0:self.placeCount]]
			actmin = acts.index(min(acts))
			self.memoryUpdate(actmin)
			return self.rehearse(self.placeCount, actmin, latency)

############################################################################################################	
	def getNextFlashcardPlace(self):
		# has the subject guessed all places in the batch correctly in a row?
		#lastFlashResults = self.scoreHistory[-2:-9:-2] #scores are interleaved with spacing
		#print 'FLASHCARD ', self.flashcardResults, self.flashcardBatchOffset
		#print 'SUM', sum(self.flashcardResults)
		if sum(self.flashcardResults) == 4 and self.flashcardBatchOffset == 3:
			# was it the first time we showed this batch?
			if self.mapPlaces[(self.numPlaces // 2) + self.flashcardBatch*4].numShows > 1:
				# if not, time for the next batch
				#print 'NEXT BATCH'
				self.flashcardBatch = (self.flashcardBatch+1) % 4
			
			self.flashcardBatchOffset = 0
			if self.flashcardBatch > 3: #we've done everything: reset
				self.flashcardBatch = 0
				
		else:
			# get the next place of the current batch
			self.flashcardBatchOffset = (self.flashcardBatchOffset+1) % 4

		# get the next place
		place = (self.numPlaces // 2) + self.flashcardBatch*4 + self.flashcardBatchOffset
		self.mapPlaces[place].addShow()
		type = TRIAL
		# has this place been presented before?
		if not self.mapPlaces[place].shownBefore:
			type = DRILL
			self.mapPlaces[place].shownBefore = True
		
		return (place, type)

	def getNextCalibTrial(self):
		self.calibCounter += 1
		idx = self.calibCounter

		return idx
	
	def doneCalibrating(self):
		if self.calibCounter < self.maxCalib-1:
			return False
		else:
			# we're done calibrating
			totalDist = sum([c.distanceTraveled for c in self.completedCalibTrials[2:]])
			totalTime = sum([c.RT for c in self.completedCalibTrials[2:]])
			self.estimatedAvgSpeed = totalDist / totalTime
			#print 'time estimated from calibration ',self.estimatedAvgSpeed
			return True
		#return not (self.calibCounter < self.maxCalib-1)
	
	# use the result of the trial (right/wrong, hint/no hint) to update the teacher
	def currentTrialResult(self, trialResult, hintUsed, rt, velocity, distance, shortest, timestamp):
		name = self.mapPlaces[self.currentTrialPlace].name
		self.completedTrials.append(TrialResult(self.trialType, self.trialCondition, self.currentTrialPlace, name, trialResult, hintUsed, rt, velocity, distance, shortest, timestamp))
		self.scoreHistory.append(trialResult)
		
		#print 'RESULT ',trialResult
		if self.trialCondition == FLASHCARD:
			#print 'UPDATE FC'
			self.flashcardResults[self.flashcardBatchOffset] = trialResult
		
		return True
	
	def currentCalibrationResult(self, rt, velocity, distance, shortest, timestamp):
		self.completedCalibTrials.append(TrialResult(CALIB, 0, self.calibCounter, '', 1, False, rt, velocity, distance, shortest, timestamp))
	
	def percentageCorrect(self, numTrials):
		trials = self.scoreHistory[-numTrials:]
		if len(trials) == 0:
			return 100
		else:
			return int( (sum(trials) / len(trials))*100 )
		
	def  currentTrialPlaceCoords(self):
		return (self.mapPlaces[self.currentTrialPlace].x, self.mapPlaces[self.currentTrialPlace].y)

	def  currentCalibCoords(self):
		return (self.calibPlaces[self.calibCounter].x, self.calibPlaces[self.calibCounter].y)
		
	def  currentTrialPlaceSize(self):
		return self.mapPlaces[self.currentTrialPlace].size
		
	def currentTrialPlaceName(self):
		return self.mapPlaces[self.currentTrialPlace].name
	
	def getPlace(self, i):
		return self.mapPlaces[i]
		
	def getCalib(self, i):
		return self.calibPlaces[i]
	
	def saveResults(self):
		prefix = str(int(time.time()))
		
		# save results for spss
		spssHeader = 'Subject\tTrialtype\tCondition\tPlacename\tSuccess\tHintUsed\tTimestamp\tRT\tAvgspeed\tAvgvelocity\tTravdistance\tShortestpath\n'
		
		spssFull = ''
		spssFlash = ''
		spssSpacing = ''
		
		#save xml for plotting later
		xmlFull = xml.dom.minidom.Document()
		xmlres = xmlFull.createElement("results")
		xmlres.setAttribute("subject", prefix)
		xmlres.setAttribute("date", self.date)
		xmlres.setAttribute("subjectname", self.subjectName)
		xmlFull.appendChild(xmlres)
		
		#format the place information
		for (i, place) in enumerate(self.mapPlaces):
			xmlDat = xmlFull.createElement("place")
			condition = FLASHCARD
			if self.spacingFirst:
				if i < 16:
					condition = SPACING
			else:
				if i >= 16:
					condition = SPACING
			xmlDat.setAttribute("condition", str(condition))
			xmlDat.setAttribute("name", place.name)
			xmlDat.setAttribute("totalpresentations", str(place.numShows))
			xmlDat.setAttribute("i", str(i))
			#xmlDat.setAttribute("firstpresentation", place.times[0])
			
			if len(place.times) > 0:
				for (i,times) in enumerate(place.times):
					placeTime = xmlFull.createElement("pres")
					placeTime.setAttribute("time", str(times))
					placeTime.setAttribute("i", str(i))
					xmlDat.appendChild(placeTime)
			if len(place.decays) > 0:
				for (i,decay) in enumerate(place.decays):
					placeDecay = xmlFull.createElement("decay")
					placeDecay.setAttribute("value", str(decay))
					placeDecay.setAttribute("i", str(i))
					xmlDat.appendChild(placeDecay)
			if len(place.alpha) > 0:
				for (i,a) in enumerate(place.alpha):
					placeAlpha = xmlFull.createElement("alpha")
					placeAlpha.setAttribute("value", str(a))
					placeAlpha.setAttribute("i", str(i))
					xmlDat.appendChild(placeAlpha)
	
			xmlres.appendChild(xmlDat)
			
		#format the trial results for analysis
		for trial in self.completedTrials:
			#spss
			spssDat =  prefix+'\t'+str(trial.type-1)+'\t'+str(trial.condition)+'\t'+str(trial.placeName)+'\t'+str(trial.result)
			spssDat += '\t'+str(trial.hintUsed)+'\t'+str(trial.timeStamp)+'\t'+str(trial.RT)+'\t'+str(trial.avgSpeed)+'\t'
			spssDat += str(trial.avgVelocity)+'\t'+str(trial.distanceTraveled)+'\t'+str(trial.shortestPath)+'\n'
			spssFull += spssDat
			if trial.condition == SPACING:
				spssSpacing += spssDat
			else:
				spssFlash += spssDat
			#xml
			xmlDat = xmlFull.createElement("trial")
			xmlDat.setAttribute("trialtype", str(trial.type-1))
			xmlDat.setAttribute("condition", str(trial.condition))
			xmlDat.setAttribute("placename", str(trial.placeName))
			xmlDat.setAttribute("success", str(trial.result))
			xmlDat.setAttribute("hintused", str(trial.hintUsed))
			xmlDat.setAttribute("timestamp", str(trial.timeStamp))
			xmlDat.setAttribute("rt", str(trial.RT))
			xmlDat.setAttribute("avgspeed", str(trial.avgSpeed))
			xmlDat.setAttribute("avgvelocity", str(trial.avgVelocity))
			xmlDat.setAttribute("travdistance", str(trial.distanceTraveled))
			xmlDat.setAttribute("shortestpath", str(trial.shortestPath))
			xmlres.appendChild(xmlDat)
		
		spssAll = open('results/'+prefix+'_all.txt','w')
		spssAll.write(spssHeader+spssFull)
		#spssSp = open('results/'+prefix+'_spacing.txt','w')
		#spssSp.write(spssHeader+spssSpacing)
		#spssFl = open('results/'+prefix+'_flash.txt','w')
		#spssFl.write(spssHeader+spssFlash)	

		xmlFile = open('results/'+prefix+'.xml','w')
		xmlFull.writexml(xmlFile, "    ", "  ", "\n", "UTF-8")
		return True

	
# Represents a place on the map
class Place(object):
	def __init__(self, x=0, y=0, name='None', size=0.8):
		self.x = x
		self.y = y
		self.name = name
		self.size = size
#############################################################################################
		self.times = []		#The list of response times per item
		self.decays = []	#The list of decay values per item
		self.alpha = []		#The list of alpha's for each item
		self.act = 0		#The activation per item
		self.numShows = 0 	#The # of shows per item
		
		self.shownBefore = False

	def addShow(self):
		self.numShows += 1
###########################################################################################                
	def hit(self, x, y):
		distanceSqr = (self.x-x)*(self.x-x) + (self.y-y)*(self.y-y)
		if distanceSqr <= placeClickAreaSqr:
			return True
		else:
			return False
	
	def distanceTo(self, x, y):
		return sqrt( (self.x-x)*(self.x-x) + (self.y-y)*(self.y-y) )

	def coords(self):
		return (self.x, self.y)
	
		return False

class TrialResult(object):
	def __init__(self, type, condition, placeIdx, placeName, result, hintUsed, rt, velocity, distance, shortest, timestamp):
		self.type = type
		self.condition = condition
		self.placeIndex = placeIdx
		self.placeName = placeName
		self.result = result
		self.hintUsed = hintUsed
		self.RT = rt
		self.avgVelocity = velocity
		self.distanceTraveled = distance
		if rt > 0:
			self.avgSpeed = distance / rt
		else:
			self.avgSpeed = 1000
		self.shortestPath = shortest
		self.timeStamp = timestamp
		
# App handles the window, initialization and scheduling
class App(pyglet.window.Window):
	def __init__(self, subject, spacing, *args, **keys):
		super(App, self).__init__(*args, **keys)

		self.subjectName = subject
		self.spacingFirst = spacing
		
		# variables that define the state of the program
		self.runTime = 0.0              # internal clock
		self.subjectTime = 0.0          # starts running when the subject starts
		self.expLength = 20*60.0      # total experiment length
		self.maxTrialLen = 15.0         # maximal length of a trial
		self.trialStartTime = 0.0       # time the user starts a new trial by clicking ok
		self.posFeedbackLen = 0.75      # amount of time positive feedback is shown
		self.posFeedbackTimer = 0.0     # keeps track of positive feedback time
		self.negFeedbackLen = 2.0       # amount of time positive feedback is shown
		self.negFeedbackTimer = 0.0     # keeps track of positive feedback time		
		self.mode = INTRO               # the current mode the program is in. 0 is the welcomescreen
		self.showNextPlaceBox = False  #is the next place the user must find shown?
		self.clickedCorrectPlace = False
		self.clickedWrongPlace = False
		self.trialTimedOut = False
		self.showHint = False
		self.allowHint = False
		
		self.currentTrialPlace = 0 #self.teacher.getNextTrial() # the current place the subject must find
		self.currentTrialType = DRILL
		
		# calibration phase stuff
		self.calibPlace = 0
		
		#information relating to the pointer/mouse
		self.mousePos = (self.width//2, self.height//2)
		self.prevMousePos = self.mousePos
		self.distanceTraveled = 0 # cityblok distance traveled in one trial
		self.velocityMeasures = [] # mouse velocities measured for one trial
		self.shortestPath = 0 # shortest path from trial starting pos to target
		self.mouseUpdated = False
		self.clickedPlace = 0 # place clicked by the subject

		#initialize teacher with the list of map places
		mapPlaces = self.loadMapPlaces()
		self.teacher = Teacher(mapPlaces, self.width, self.height, self.spacingFirst, self.expLength, self.subjectName) 
		
		#setup gui
		self.gui = Gui(self.width, self.height, mapPlaces, self.teacher.calibPlaces)

		#setup animations
		self.ani = Animator(self.width, self.height, self.posFeedbackLen, self.negFeedbackLen)

		# nicer graphics
		glEnable(GL_BLEND)
		glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA) 
		
	######### GRAPHICS #########
	
	# Drawing loop
	def on_draw(self):
		self.clear()

		if self.mode == INTRO:
			self.gui.drawIntroScreen()
		elif self.mode == END:
			self.gui.drawEndScreen()		
		else:
			self.gui.drawMap()		
			
			if self.mode == CALIB:
				self.gui.drawCalibBackground()
				self.gui.drawCalibMarkers()
			else:
				if self.showHint:
					self.gui.drawHintArea()
				self.gui.drawMarkers()
		
			if self.clickedCorrectPlace:
				self.gui.drawCorrectMarker()

			if self.clickedWrongPlace:
				self.gui.drawWrongMarker()
				
			self.ani.renderMapAnimations()
		
			self.gui.drawGuiElements()
			
			self.ani.renderOverlayAnimations(self.currentTrialType)

	
	######### DEAL WITH INPUT #########
	
	# Find out which place was clicked by the user
	def getClickedPlace(self, x, y):
		places = []
		if (self.mode == CALIB):
			places = self.teacher.calibPlaces
		else:
			places = self.teacher.mapPlaces
		
		for (i, place) in enumerate(places):
			if place.hit(x,y):
				return i
		return None

	# update the amount the mouse as moved, using a 'city block' distance measure
	def updateDistanceTraveled(self, dx, dy):
		self.distanceTraveled += abs(dx) + abs(dy)
	
	# submit information of the completed trial to the teacher object
	def updateTeacherWithTrial(self, result):
		avgVelocity = sum(self.velocityMeasures) / len(self.velocityMeasures)
		hint = NOHINT
		if self.showHint:
			hint = HINT
		self.teacher.currentTrialResult(result, hint, (self.subjectTime - self.trialStartTime), avgVelocity, self.distanceTraveled, self.shortestPath, self.subjectTime)
		self.resetMeasurements()	
	
	# start all the processes when the subject has clicked a correct place
	def startClickedCorrectPlace(self):	
		self.updateTeacherWithTrial(CORRECT)

		self.clickedCorrectPlace = True
		self.showHint = False		
		
		# change place marker
		(px, py) = self.teacher.currentTrialPlaceCoords()
		self.gui.setClickedMarker(True, self.currentTrialPlace, px, py, self.teacher.currentTrialPlaceSize())
		if self.currentTrialType == DRILL:
			self.ani.endArrowAni()		
		# animations
		self.ani.finishPlacePopup()
		self.ani.startClickPlaceAni(px, py)
		self.ani.startPosFeedbackAni(px, py)

	# update the animations and such
	def calcClickedCorrectPlace(self, dt):
		if self.clickedCorrectPlace:
			self.posFeedbackTimer += dt
			
			if self.posFeedbackTimer > self.posFeedbackLen:
				 self.finishedClickedCorrectPlace()
	
	# done with all the positive feedback, start the next trial
	def finishedClickedCorrectPlace(self):
		# finalize the place click
		self.clickedCorrectPlace = False
		self.posFeedbackTimer = 0.0
		self.gui.unsetClickedMarker(True, self.currentTrialPlace)
		self.clickedPlace = 0
		
		# start a new trial
		self.startNextTrial()
		
	def startClickedWrongPlace(self):
		self.updateTeacherWithTrial(WRONG)

		self.clickedWrongPlace = True
		self.showHint = False		
		
		(px, py) = self.teacher.getPlace(self.clickedPlace).coords()
		self.gui.setClickedMarker(False, self.clickedPlace, px, py, self.teacher.getPlace(self.clickedPlace).size)		
		if self.currentTrialType == DRILL:
			self.ani.endArrowAni()
		self.ani.finishPlacePopup()
		self.ani.startClickPlaceAni(px, py)
		
		(tx, ty) = self.teacher.currentTrialPlaceCoords()
		self.ani.startNegFeedbackAni(tx, ty)
		
	def calcClickedWrongPlace(self, dt):
		if self.clickedWrongPlace:
			self.negFeedbackTimer += dt
			
			if self.negFeedbackTimer > self.negFeedbackLen:
				 self.finishedClickedWrongPlace()
				 
	def finishedClickedWrongPlace(self):	
		self.clickedWrongPlace = False
		self.negFeedbackTimer = 0.0
		self.gui.unsetClickedMarker(False, self.clickedPlace)
		self.clickedPlace = 0
		
		self.startNextTrial()

	# if a subject waits too long before answering, the trial times out
	def startTimedOut(self):	
		self.updateTeacherWithTrial(WRONG)

		self.trialTimedOut = True
		self.showHint = False
		self.ani.finishPlacePopup()
		(tx, ty) = self.teacher.currentTrialPlaceCoords()
		self.ani.startNegFeedbackAni(tx, ty)		

	def calcTimedOut(self, dt):
		if self.trialTimedOut:
			self.negFeedbackTimer += dt
			
			if self.negFeedbackTimer > self.negFeedbackLen:
				 self.finishedTimedOut()	

	def finishedTimedOut(self):
		self.trialTimedOut = False
		self.negFeedbackTimer = 0.0
		
		self.startNextTrial()

	def calcShowHint(self, dt):
		if self.subjectTime - self.trialStartTime > 0.66*self.maxTrialLen and not self.showHint:
			if self.allowHint:
				#print 'show hint'
				self.showHint = True
		
	def resetMeasurements(self):
		self.velocityMeasures = []
		self.distanceTraveled = 0
		self.shortestPath = 0		
		
	# check to see which place was clicked, if any
	def handleMapClickInput(self, x, y):
		# what place did the subject click
		placeIdx = self.getClickedPlace(x, y)
		self.clickedPlace = placeIdx
		if placeIdx != None: # a place was clicked
			# is it the right place?
			if placeIdx == self.currentTrialPlace: #right
				self.startClickedCorrectPlace()
			else: #wrong
				self.startClickedWrongPlace()

	def handleCalibClickInput(self, x, y):
		placeIdx = self.getClickedPlace(x, y)
		self.clickedPlace = placeIdx
		#print placeIdx
		if placeIdx != None: # a place was clicked
			(px, py) = self.teacher.getCalib(placeIdx).coords()
			self.ani.startClickPlaceAni(px, py)
			if placeIdx == self.calibPlace: #right
				avgVelocity = sum(self.velocityMeasures) / len(self.velocityMeasures)
				self.teacher.currentCalibrationResult( (self.subjectTime - self.trialStartTime), avgVelocity, self.distanceTraveled, self.shortestPath, self.subjectTime)
				self.clickedPlace = 0
				self.resetMeasurements()
				self.ani.endArrowAni()
				self.startNextCalib()
			else: # wrong, reset
				self.resetMeasurements()
				self.trialStartTime = self.subjectTime
				(tx, ty) = self.teacher.currentCalibCoords()
				self.ani.endArrowAni()
				self.ani.startArrowAni(tx, ty)
				self.clickedPlace = 0
				
	def handleIntroScreenInput(self, x, y):
		pass
	
	######### TIMING #########
	
	# keep track of time
	def updateTime(self, dt):
		self.runTime += dt
		self.subjectTime += dt
		#print self.timeRunning

	# check how long this trial has been going on
	def checkTrialTime(self):
		if (self.subjectTime - self.trialStartTime) > self.maxTrialLen and not self.trialTimedOut and not self.clickedCorrectPlace and not self.clickedWrongPlace:
			#time up, count it as wrong
			self.startTimedOut()
			
	# measure pointer speed frame to frame
	def pointerVelocity(self, dt):
		(x, y) = self.mousePos
		(px, py) = self.prevMousePos
		
		velocity = sqrt( pow(x-px, 2) + pow(y-py, 2) )
		self.velocityMeasures.append(velocity)
		
	# run animations when apropriate
	def update(self, dt):
		#compensation for the mouse position only being updated when moved
		if not self.mouseUpdated:
			self.prevMousePos = self.mousePos

		self.updateTime(dt)
		self.pointerVelocity(dt)
		if self.mode == DRILL or self.mode==TRIAL:
			self.checkTrialTime()
			if  not self.clickedCorrectPlace and not self.clickedWrongPlace and not self.trialTimedOut:
				self.calcShowHint(dt)
		self.ani.updateAnimations(dt)
		self.calcClickedCorrectPlace(dt)
		self.calcClickedWrongPlace(dt)
		self.calcTimedOut(dt)
		
		self.mouseUpdated = False
		
	######## INPUT EVENTS #########
	
	def on_mouse_press(self,x, y, button, modifiers):
		#print x,y
		# what mode are we in? (before trial, during trial, training, etc.)
		if self.mode == TRIAL or self.mode == DRILL: # subject can click places
			if not self.clickedCorrectPlace and not self.clickedWrongPlace and not self.trialTimedOut: # not busy handling a previous trial	
				# subject has already initiated the new (practice) trial
				self.handleMapClickInput(x, y)
		elif self.mode == CALIB:
			self.handleCalibClickInput(x, y)
		elif self.mode == INTRO:
			self.handleIntroScreenInput(x, y)
	
	def on_mouse_motion(self, x, y, dx, dy):
		self.mouseUpdated = True
		self.prevMousePos = self.mousePos
		self.mousePos = (x, y)
		
		self.updateDistanceTraveled(dx, dy)
	
	def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
		if self.mode == TRIAL or self.mode == DRILL:
			self.updateDistanceTraveled(dx, dy)
	
	def on_key_release(self, symbol, modifiers):
		if self.mode == INTRO:
			if symbol == pyglet.window.key.SPACE:
				self.startCalibration()

	def on_close(self):
		if self.mode != END:
			#we didn't save the data for some reason, do so now
			self.teacher.saveResults()
		super(App, self).on_close()
				
	######### MISC #########
	
	def startCalibration(self):
		self.mode = CALIB
		self.subjectTime = 0.0
		self.startNextCalib()
	
	# called once at the beginning of the experiment
	def startExperiment(self):
		self.mode = DRILL
		self.subjectTime = 0.0
		self.startNextTrial()
	
	def startNextCalib(self):
		if not self.teacher.doneCalibrating():
			self.calibPlace = self.teacher.getNextCalibTrial()
			(tx, ty) = self.teacher.currentCalibCoords()
			(mx, my) = self.mousePos
			
			self.trialStartTime = self.subjectTime
			self.shortestPath = abs(tx-mx) + abs(ty-my) # in 'city blocks'
			
			self.ani.startArrowAni(tx, ty)
		else:
			self.startExperiment()
	
	def startNextTrial(self):
		self.showHint = False
		# check if there's time for another trial
		if self.subjectTime < self.expLength:
			# get a new trial from the teacher
			(newPlace, type, hintAllowed) = self.teacher.getNextTrial(self.subjectTime)
			#print 'newplace ',newPlace
			self.currentTrialPlace = newPlace
			self.currentTrialType = type
			self.allowHint = hintAllowed
			
			# get the shortest path between the mouse and the new trial
			(tx, ty) = self.teacher.currentTrialPlaceCoords()
			(mx, my) = self.mousePos
			self.shortestPath = abs(tx-mx) + abs(ty-my) # in 'city blocks'
			self.trialStartTime = self.subjectTime

			#setup hint area
			self.gui.setHintArea(tx, ty)
			
			self.ani.startPlacePopupAni(self.teacher.currentTrialPlaceName())
			self.gui.updateScoreFeedback(10, self.teacher.percentageCorrect(10))
			
			if self.currentTrialType == DRILL: # show the arrow
				self.ani.startArrowAni(tx, ty)
		else:
			self.finalizeExperiment()
	
	# save stuff, show ending screen
	def finalizeExperiment(self):
		# save results
		self.teacher.saveResults()
		
		# show end screen
		self.mode = END
	
	# Load countries from an xml file
	def loadMapPlaces(self):
		doc = xml.dom.minidom.parse('map.xml')
		places = []
		
		for node in doc.getElementsByTagName('place'):
			x = node.getAttribute('x')
			y = node.getAttribute('y')
			name = node.getAttribute('name')
			size = node.getAttribute('size')
		
			places.append(Place(int(x), int(y), name, float(size)))
		
		doc.unlink()
		return places			

# Display animations
class Animator(object):
	def __init__(self, screenWidth, screenHeight, posFbLen, negFbLen):
		self.width = screenWidth
		self.height = screenHeight
		
		self.aniClickGlowLen = 0.3
		self.posFeedbackLen = posFbLen
		self.negFeedbackLen = negFbLen
		self.showArrowLen = 7.0
		
		self.showClickGlowAni = False       #show glow when clicking a place
		self.aniClickGlowTime = 0.0
		self.showPosFeedbackAni = False  #show positive feedback
		self.posFeedbackTime = 0.0
		self.showNegFeedbackAni = False  #show positive feedback
		self.negFeedbackTime = 0.0
		self.showArrowAni = False # show the place indicator arrow
		self.arrowTime = 0.0
		
		self.showPlacePopupAni = False
		self.placePopupTime = 0.0
		self.finishPopup = False
		
		self.posFeedbackColor = (0,69,89)
		self.negFeedbackColor = (181,0,0)
		
		self.initGraphics()

	def initGraphics(self):
		# the glow shown when a place is clicked
		self.imgClickGlow = loadAndCenterImg('img/glow.png')
		self.clickGlow = createSprite(self.imgClickGlow)

		# popup showing the next trial place
		self.imgPlacePopup = loadAndCenterImg('img/place_popup.png')
		self.placePopup = createSprite(self.imgPlacePopup, x=self.width//2, y=self.height-50)
		
		# box containing feedback
		self.imgFeedbackBox = loadAndCenterImg('img/feedback_box.png')
		self.feedbackBox = createSprite(self.imgFeedbackBox)
		self.feedbackBox.scale = 0.8
		
		#arrow used in  negative feedback and drill trials
		self.imgArrow = loadAndCenterImg('img/arrow.png')
		self.arrow = createSprite(self.imgArrow)
		self.arrow.scale = 0.6
		
		self.textPosFeedback = pyglet.text.Label('Right!', font_name=appFont,  font_size=18,  bold=True, x=0, y=0,  anchor_x='center', anchor_y='center')
		self.textNegFeedback = pyglet.text.Label('Wrong!', font_name=appFont,  font_size=18,  bold=True, x=0, y=0,  anchor_x='center', anchor_y='center')
		self.textNegFeedback2 = pyglet.text.Label('It\'s here', font_name=appFont,  font_size=16,  bold=True, x=0, y=0,  anchor_x='center', anchor_y='center')
		self.textTrial = pyglet.text.Label('Where is', font_name=appFont,  font_size=16,  x=self.width//2, y=self.height-35,  anchor_x='center', anchor_y='center')
		self.textDrill = pyglet.text.Label('Learn', font_name=appFont,  font_size=16,  x=self.width//2, y=self.height-35,  anchor_x='center', anchor_y='center')
		self.textDrill.color = (0, 0, 0, 255)
		self.textTrialPlace = pyglet.text.Label(' ', font_name=appFont,  bold=True, font_size=22,  x=self.width//2, y=self.height-60,  anchor_x='center', anchor_y='center')
		
	def renderMapAnimations(self):
		if self.showClickGlowAni:
			self.clickGlow.draw()
		
		if self.showPosFeedbackAni:
			self.feedbackBox.draw()
			self.textPosFeedback.draw()
			
		if self.showNegFeedbackAni:
			self.feedbackBox.draw()
			self.arrow.draw()
			self.textNegFeedback.draw()
			self.textNegFeedback2.draw()
			
		if self.showArrowAni:
			self.arrow.draw()

	def renderOverlayAnimations(self, trialType):
		if self.showPlacePopupAni:
			
			if trialType == TRIAL:
				self.placePopup.color = (255, 255, 255)
				self.placePopup.draw()
				self.textTrial.draw()
			else:
				self.placePopup.color = (150, 255, 165)
				self.placePopup.draw()
				self.textDrill.draw()
			self.textTrialPlace.draw()
			
	def updateAnimations(self, dt):
		self.calcClickPlaceAni(dt)
		self.calcPosFeedbackAni(dt)
		self.calcNegFeedbackAni(dt)
		self.calcPlacePopupAni(dt)
		self.calcArrowAni(dt)

	## ANIMATIONS
		
	def startClickPlaceAni(self, x, y):
		#reposition glow animation
		self.clickGlow.set_position(x, y)
		self.clickGlow.scale = 0.2
		self.clickGlow.opacity = 255
		self.clickGlow.visible = True
		self.showClickGlowAni = True
	
	def calcClickPlaceAni(self, dt):
		if self.showClickGlowAni:
			self.aniClickGlowTime += dt
			if self.aniClickGlowTime > self.aniClickGlowLen:
				# animation is done
				self.endClickPlaceAni()
			else:
				# continue animation
				self.clickGlow.scale = 0.3 + (0.6*self.aniClickGlowTime)/self.aniClickGlowLen
				self.clickGlow.opacity = 255 - int( (255*self.aniClickGlowTime)/self.aniClickGlowLen )	
	
	def endClickPlaceAni(self):
		self.clickGlow.visible = False
		self.showClickGlowAni = False
		self.aniClickGlowTime = 0.0


	def startPlacePopupAni(self, placeName):
		self.placePopup.visible = True
		self.showPlacePopupAni = True
		self.textTrialPlace.text = placeName
	
	def calcPlacePopupAni(self, dt):
		fadeLen = 0.2
		if self.showPlacePopupAni:

			if self.finishPopup: # do fade out
				if self.placePopupTime > fadeLen*2:
					self.endPlacePopupAni()
				else:
					self.placePopupTime += dt
					alpha =  max(0, 255 - int( (255*(self.placePopupTime-fadeLen)/fadeLen) ))
					self.placePopup.opacity = alpha
					self.textTrialPlace.color = (0, 0, 0, alpha)
					self.textTrial.color = (0, 0, 0, alpha)
					self.placePopup.scale = 0.9 + 0.2*((self.placePopupTime-fadeLen)/fadeLen)
			
			elif self.placePopupTime < fadeLen: #do fade in
				self.placePopupTime += dt
				alpha = min(255, int( (255*self.placePopupTime)/fadeLen))
				self.placePopup.opacity = alpha
				self.textTrialPlace.color = (0, 0, 0, alpha)
				self.textTrial.color = (0, 0, 0, alpha)
				self.placePopup.scale = 1.0 - 0.2*(self.placePopupTime/fadeLen)
	
	def endPlacePopupAni(self):
		self.placePopup.visible = False
		self.showPlacePopupAni = False
		self.finishPopup = False
		self.placePopupTime = 0.0
	
	def finishPlacePopup(self):
		self.finishPopup = True
	
	def startPosFeedbackAni(self, x, y):
		#determine where to show the feedback
		self.feedbackBox.set_position(x, y+70)
		self.textPosFeedback.x = x
		self.textPosFeedback.y = y + 70
		(posR, posG, posB) = self.posFeedbackColor
		self.feedbackBox.visible = True
		self.textPosFeedback.color = (posR, posG, posB, 0)
		self.showPosFeedbackAni = True
		
	def calcPosFeedbackAni(self, dt):
		if self.showPosFeedbackAni:
			#we're in the middle of the animation
			self.posFeedbackTime += dt
			if self.posFeedbackTime > self.posFeedbackLen:
				self.endPosFeedbackAni()
			else:
				fadeLen = self.posFeedbackLen*0.2
				(posR, posG, posB) = self.posFeedbackColor
				feedbackAlpha = self.getFeedbackAlpha(self.posFeedbackTime, fadeLen, self.posFeedbackLen)
				
				self.textPosFeedback.color =  (posR, posG, posB, feedbackAlpha)
				self.feedbackBox.opacity = feedbackAlpha
				
	def endPosFeedbackAni(self):
		self.showPosFeedbackAni = False
		self.feedbackBox.visible = False
		self.posFeedbackTime = 0.0	

	def calcFeedbackAni(self, positive, dt):	
		if positive:
			showFeedbackAni = self.showPosFeedbackAni
		else:
			showFeedbackAni = self.showNegFeedbackAni
		
	def startNegFeedbackAni(self, x, y):
		#determine where to show the feedback
		self.feedbackBox.set_position(x, y+100)
		self.arrow.set_position(x, y+30)
		self.textNegFeedback.x = x
		self.textNegFeedback.y = y + 115
		self.textNegFeedback2.x = x
		self.textNegFeedback2.y = y + 85
		(posR, posG, posB) = self.negFeedbackColor
		self.feedbackBox.visible = True
		self.arrow.visible = True
		self.textNegFeedback.color = (posR, posG, posB, 0)
		self.textNegFeedback2.color = (posR, posG, posB, 0)
		self.showNegFeedbackAni = True

	def calcNegFeedbackAni(self, dt):
		if self.showNegFeedbackAni:
			#we're in the middle of the animation
			self.negFeedbackTime += dt
			if self.negFeedbackTime > self.negFeedbackLen:
				self.endNegFeedbackAni()
			else:
				fadeLen = self.negFeedbackLen*0.15
				(negR, negG, negB) = self.negFeedbackColor
				feedbackAlpha = self.getFeedbackAlpha(self.negFeedbackTime, fadeLen, self.negFeedbackLen)
				
				self.textNegFeedback.color = (negR, negG, negB, feedbackAlpha)
				self.textNegFeedback2.color = (negR, negG, negB, feedbackAlpha)
				self.feedbackBox.opacity = feedbackAlpha
				self.arrow.opacity = feedbackAlpha
		
	def endNegFeedbackAni(self):		
		self.showNegFeedbackAni = False
		self.feedbackBox.visible = False
		self.arrow.visible = False
		self.negFeedbackTime = 0.0

	def startArrowAni(self, x, y):
		self.showArrowAni = True
		self.arrow.set_position(x, y+30)
		self.arrow.visible = True
		self.arrow.opacity = 0

	def calcArrowAni(self, dt):
		if self.showArrowAni:
			self.arrowTime  += dt
			if self.arrowTime > self.showArrowLen:
				self.endArrowAni()
			else:
				fadeLen = self.showArrowLen*0.10
				self.arrow.opacity = min(255, int(255*(self.arrowTime/fadeLen)))

	def endArrowAni(self):
		self.showArrowAni = False
		self.arrow.visible = False
		self.arrowTime = 0.0
		self.arrow.opacity = 0
				
	## MISC
	
	def getFeedbackAlpha(self, aniTime, fadeLength, aniLength):
		if aniTime < fadeLength:
			return int(255*(aniTime/fadeLength))
		elif aniTime  > aniLength - fadeLength:
			len = aniTime - aniLength + fadeLength
			return 255 - int(255*(len/fadeLength))
		else:
			return 255

#Draw and update the gui
class Gui(object):
	def __init__(self, screenWidth, screenHeight, mapPlaces, calibPlaces):
		self.width = screenWidth
		self.height = screenHeight
		
		self.initGraphics()
		self.loadPlaceMarkers(mapPlaces)
		self.loadCalibMarkers(calibPlaces)
	
	## SETUP
	
	def initGraphics(self):
		#bar at the top of the screen
		imgTopbar = pyglet.image.load('img/topbar.png')
		self.texTopbar = imgTopbar.get_texture()
		
		#get the map
		self.imgMap = pyglet.image.load('img/map.png')	
		self.placeMarkers = [] #place marker sprites
		self.placeRadii = []
		self.placeMarkersBatch = pyglet.graphics.Batch() #improve rendering by batching

		self.hintArea = (0,0,1,1)
		
		#calibration stuff
		self.calibMarkers = []
		self.calibRadii = []
		self.calibMarkersBatch = pyglet.graphics.Batch()
		
		self.imgGrid = loadAndCenterImg('img/grid.png')		
		self.grid = pyglet.image.TileableTexture.create_for_image(self.imgGrid)
		self.gridWidth = self.width / self.imgGrid.width
		self.gridHeight = self.height / self.imgGrid.height
		
		#setup place marker rendering
		self.imgPlaceMarker = loadAndCenterImg('img/marker.png')
		self.imgMarkerCorrect = loadAndCenterImg('img/marker_right.png')
		self.markerCorrect = createSprite(self.imgMarkerCorrect)
		self.imgMarkerWrong = loadAndCenterImg('img/marker_wrong.png')
		self.markerWrong = createSprite(self.imgMarkerWrong)
		self.imgPlaceRadius = loadAndCenterImg('img/radius.png')

		# intro images
		self.imgIntro1 = loadAndCenterImg('img/intro_click.png')
		self.imgIntro2 = loadAndCenterImg('img/intro_arrow.png')
		
		#setup text
		self.textPercentCorrect = pyglet.text.Label(' ', font_name=appFont,  font_size=14,  x=self.width-10, y=self.height-10,  anchor_x='right', anchor_y='top')
		self.textPercentCorrect.color = (0,0,0,255) #black

		introText ='''<font face=%s size=20><b>Hello participant!</b> Welcome to <i>Adaptive Topographic Learning</i>. 
						 <br><br> We are very glad you want to be part of this experiment.
<br><br> In this experiment you will learn a group of places in South Africa. In every trial the place you need to find is indicated at the top of the screen. You can do so by clicking the place on the map. Clicking anywhere inside the circle surrounding a place marker will select that place. 
<br><br> The first presentation of a place will be a learning trial. Of course you have not practised this place, and the program will help you to find the place by placing an arrow above it.
<br><br> You only have a limited amount of time to click the correct place. If you are not quick enough a hint may appear to help you. The correct position of the place will then be somewhere inside the area shown by the hint. If you are still unsure about the correct answer, you will be given a new place to find. 
<br><br> After each question you will be given feedback (right or wrong). If you were wrong, the correct answer will be shown. You do not need to click it.
<br><br>Before we begin, there is a short calibration session to get an idea about your average mouse movement. You will not be asked to find actual places, but simply need to click the marker with an arrow above it.
<br><br><b>Please press the spacebar to start.</b></font>''' % appFont
		self.textIntro = pyglet.text.HTMLLabel(introText, width=600, multiline=True,  x=self.width//2, y=self.height//2,  anchor_x='center', anchor_y='center')
		self.textIntro.color = (0,0,0,255)
	   
		endText ='''<font face=%s size=20><b>Thank you for participating!</b><br><br>
						The results have been saved and you can now close this program.</font>''' % appFont
						 
		self.textEnd = pyglet.text.HTMLLabel(endText, width=600, multiline=True,  x=self.width//2, y=self.height//2,  anchor_x='center', anchor_y='center')
		self.textEnd.color = (0,0,0,255)
		
	# Load the sprites of the placemarkers into a batch
	def loadPlaceMarkers(self, mapPlaces):
		for place in mapPlaces:
			(newMarker, newRadius) = self.createMarker(place.x, place.y, place.size, self.placeMarkersBatch)
			self.placeMarkers.append(newMarker)
			self.placeRadii.append(newRadius)

	def loadCalibMarkers(self, calibPlaces):
		for place in calibPlaces:
			(newMarker, newRadius) = self.createMarker(place.x, place.y, place.size, self.calibMarkersBatch)
			self.calibMarkers.append(newMarker)
			self.calibRadii.append(newRadius)
		
	def createMarker(self, px, py, size, markerBatch):
		newMarker = pyglet.sprite.Sprite(self.imgPlaceMarker, x=px, y=py, batch=markerBatch)
		newMarker.scale = size
		newRadius = pyglet.sprite.Sprite(self.imgPlaceRadius, x=px, y=py, batch=markerBatch)
		newRadius.scale = 0.65
		newRadius.opacity = 180	
		return (newMarker, newRadius)
			
	def updateScoreFeedback(self, num, percentage):
		self.textPercentCorrect.text = "Of the last %d places, you got %d%% right." % (num, percentage)
	
	def setHintArea(self, px, py):
		# get 'box' p is in
		sq = 40
		numW = int(self.width / sq)
		numH = int(self.height / sq)
		#print numH
		pbx = int(px / sq)
		pby = int(py / sq)
		#print pby
		# get min coord of hint square
		xShift = random.randrange(-1, 1)
		yShift = random.randrange(-1, 1)
		
		self.hintArea = (pbx*sq-4*sq+xShift*sq, pby*sq-4*sq+yShift*sq, pbx*sq+4*sq+xShift*sq, pby*sq+4*sq+yShift*sq)
		#print self.hintArea, px, py
		
	## DRAWING
	
	def drawMap(self):
		self.imgMap.blit(0, 0)
		
		glEnable(GL_TEXTURE_2D)
		glBindTexture(GL_TEXTURE_2D, self.grid.id)
		
		glColor4f(1.0, 1.0, 1.0, 0.3)
		pyglet.graphics.draw( 4, pyglet.gl.GL_QUADS, ('v2i',( 0,0, self.width,0, self.width,self.height, 0,self.height)),
																		   ('t2f', (0,0, self.gridWidth,0, self.gridWidth,self.gridHeight, 0,self.gridHeight)))
		glColor4f(1.0, 1.0, 1.0, 1.0)
		glDisable(GL_TEXTURE_2D)
	
	def drawHintArea(self):
		(minX, minY, maxX, maxY) = self.hintArea
		glColor4f(0.1, 0.7, 0.7, 0.4)
		pyglet.graphics.draw( 4, pyglet.gl.GL_QUADS, ('v2i',( minX,minY, maxX,minY, maxX,maxY, minX,maxY)) )
		glColor4f(1.0, 1.0, 1.0, 1.0)		
	
	def drawMarkers(self):
		self.placeMarkersBatch.draw()
	
	def drawCalibMarkers(self):
		self.calibMarkersBatch.draw()
	
	def drawCorrectMarker(self):
		self.markerCorrect.draw()	
	
	def drawWrongMarker(self):
		self.markerWrong.draw()	
	
	def drawCalibBackground(self):
		glColor4f(0.7, 0.7, 0.7, 0.9)
		pyglet.graphics.draw( 4, pyglet.gl.GL_QUADS, ('v2i',( 0,0, self.width,0, self.width,self.height, 0,self.height)) )
		glColor4f(1.0, 1.0, 1.0, 1.0)	
	
	def drawGuiElements(self):

		glEnable(GL_TEXTURE_2D)
		
		# draw the top bar
		glBindTexture(GL_TEXTURE_2D, self.texTopbar.id)
		(u1, v1, r1, u2, v2, r2, u3, v3, r3, u4, v4, r4) = self.texTopbar.tex_coords
		(tx0, tx1, ty0, ty1) = (u1+0.1,u3-0.1, v1, v3)		
		
		#pyglet.graphics.draw( 3, pyglet.gl.GL_TRIANGLES, ('v2i', (10,10, 70,10, 70,70)), ('c3i', (0,255,0, 255,0,0,0,0,255)))#('t2f', (0.0,0.0, 0.0,1.0, 1.0,1.0)) )
		n = 20
		pyglet.graphics.draw( 4, pyglet.gl.GL_QUADS, ('v2i', (-10,self.height-69+n, self.width+10,self.height-69+n, self.width+10,self.height+n, 0,self.height+n)),
		                                                                   ('t2f', (tx0,ty0,tx1,ty0,tx1,ty1,tx0,ty1)) )

		glColor4f(1.0, 1.0, 1.0, 1.0)
		glDisable(GL_TEXTURE_2D)
		
		self.textPercentCorrect.draw()		

	def drawIntroScreen(self):
		glClearColor(0.4, 0.4, 0.4, 1.0);
		self.imgMap.blit(0, 0)	
		
		glColor4f(0.7, 0.7, 0.7, 0.9)
		pyglet.graphics.draw( 4, pyglet.gl.GL_QUADS, ('v2i',( 0,0, self.width,0, self.width,self.height, 0,self.height)) )
		glColor4f(1.0, 1.0, 1.0, 1.0)		
		
		self.textIntro.draw()
		
		self.imgIntro1.blit(1000, 510)
		self.imgIntro2.blit(1000, 400)
		
	def drawEndScreen(self):
		glClearColor(0.4, 0.4, 0.4, 1.0);
		self.imgMap.blit(0, 0)	
		
		glColor4f(0.7, 0.7, 0.7, 0.9)
		pyglet.graphics.draw( 4, pyglet.gl.GL_QUADS, ('v2i',( 0,0, self.width,0, self.width,self.height, 0,self.height)) )
		self.textEnd.draw()	
		
	## UPDATING

	def setClickedMarker(self, correct, placeIdx, px, py, size):
		self.placeMarkers[placeIdx].visible = False

		if correct:
			self.changeMarker(self.markerCorrect, px, py, size)
		else:
			self.changeMarker(self.markerWrong, px, py, size)		
			
	def changeMarker(self, m, px, py, size):
		m.set_position(px, py)
		m.scale = size
		m.visible = True	
		
	def unsetClickedMarker(self, correct, placeIdx):
		self.placeMarkers[placeIdx].visible = True
		if correct:
			self.markerCorrect.visible = False
		else:
			self.markerWrong.visible = False

# Run program
if __name__ == '__main__':
	spacingFirst = True
	if len(sys.argv) > 1:
		if sys.argv[1] == 'A':
			spacingFirst = False

	subjectname = raw_input('Please type you name and press Enter: ')
	window = App(subjectname, spacingFirst, 1194, 760, caption='Adaptive Topographic Learning', vsync=False)
	pyglet.clock.schedule_interval(window.update, updateFreq)
	pyglet.app.run()
