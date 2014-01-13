import sublime
import sublime_plugin
import threading 
import os.path
from itertools import islice
from pickle import dump, load, UnpicklingError, PicklingError
from copy import deepcopy, copy

def Log(string):
	if False:
		print (string)

REGION_BASE_TAG = "__SublimeBookmark__"
SETTINGS_NAME = "SublimeBookmarks.sublime-settings"
#if someone names their project this, we're boned
NO_PROJECT = "___NO_PROJECT_PRESENT____"

BOOKMARKS = []

#list of bookmarks that have ben deleted. 
#This is used to remove bookmarks' buffer highlights. Without this, if a bookmark is removed,
#when a file is revisited, the buffer will still be marked. This will keep track of bookmarks
#that have been removed.
ERASED_BOOKMARKS = []

#whether all bookmarks (even unrelated) should be shown
SHOW_ALL_BOOKMARKS = True

class OptionsSelector:
	def __init__(self, window, panelItems, onDone, onHighlight):
		self.window = window
		self.panelItems = panelItems
		self.onDone = onDone
		self.onHighlight = onHighlight

	def run(self):
		view = self.window.active_view()
		startIndex = 0
		
		self.window.show_quick_panel(self.panelItems, self.onDone)

class OptionsInput: 
	def __init__(self, window, caption, initalText, onDone, onCancel):
		self.window = window
		self.caption = caption
		self.initalText = initalText
		self.onDone = onDone
		self.onCancel = onCancel


	def run(self):
		view = self.window.active_view()
		inputPanelView  = self.window.show_input_panel(self.caption, self.initalText, self.onDone, None, self.onCancel)
	
		#select the text in the view so that when the user types a new name, the old name
		#is overwritten
		assert (len(inputPanelView.sel()) > 0)
		selectionRegion = inputPanelView.full_line(inputPanelView.sel()[0])
		print ("DATA: " + inputPanelView.substr(selectionRegion))
		inputPanelView.sel().add(selectionRegion)
	
#helper functions--------------------------------
#Region manipulation-----------------------------
def getCurrentLineRegion(view):

	assert (len(view.sel()) > 0)
	selectedRegion = view.sel()[0]
	region =  view.line(selectedRegion)

	return region 

def markBuffer(view, bookmark):
	uid = bookmark.getUid()
	region  = bookmark.getRegion()
	view.add_regions(str(uid), [region], "text.plain", "bookmark", sublime.DRAW_OUTLINED)

def unmarkBuffer(view, bookmark):
	uid = bookmark.getUid()
	view.erase_regions(str(uid))

#Bookmark manipulation---------------------
def genUid(count):
	return REGION_BASE_TAG + str(count)
	

def gotoBookmark(bookmark, window):
	filePath = bookmark.getFilePath()
	lineNumber = bookmark.getLineNumber()

	rowCol = ":" + str(0) + ":" + str(lineNumber)

	view = window.open_file(filePath + rowCol, sublime.TRANSIENT | sublime.ENCODED_POSITION)
	view.show_at_center(bookmark.getRegion())

	#move cursor to the middle of the bookmark's region
	bookmarkRegionMid = long(0.5 * (bookmark.getRegion().begin() +  bookmark.getRegion().end()))
	moveRegion = sublime.Region(bookmarkRegionMid, bookmarkRegionMid)
	view.sel().clear()
	view.sel().add(moveRegion)


def shouldShowBookmark(bookmark, window, showAllBookmarks):
	#HACK! currentProjectPath = window.project_file_name()
	currentProjectPath = ""

	#free bookmarks can be shown. We don't need a criteria
	if showAllBookmarks:
		return True
	#there is no current project now. Show all bookmarks
	elif currentProjectPath == None or currentProjectPath == "":
		return True

	#return if the bookmark belongs to current project or not.
	else:
		return bookmark.getProjectPath() == currentProjectPath

#Menu generation-----------------------------------
def ellipsisStringEnd(string, length):
	#I have NO idea why the hell this would happen. But it's happening.
	if string is None:
		return ""
	else:
		return string if len(string) <= length else string[ 0 : length - 3] + '...'


def ellipsisStringBegin(string, length):
	if string is None:
		return ""
	else:	
		return string if len(string) <= length else '...' + string[ len(string) + 3 - (length)  : len(string) ] 

def createBookmarkPanelItems(window, bookmarks, shouldShowAllBookmarks):	
	bookmarkItems = []
	
	for bookmark in bookmarks:
		if shouldShowBookmark(bookmark, window, shouldShowAllBookmarks):

			bookmarkName = bookmark.getName()

			lineStrRaw = bookmark.getLineStr()
			bookmarkLine = ellipsisStringEnd(lineStrRaw.strip(), 55)

			bookmarkFile = ellipsisStringBegin(bookmark.getFilePath(), 55)

			bookmarkItems.append( [bookmarkName, bookmarkLine, bookmarkFile] )
		else:
			continue

	return bookmarkItems


def setStatus(statusMessage):
	sublime.status_message(statusMessage)


#Bookmark-----------
class Bookmark:
	def __init__(self, uid, name, filePath, projectPath, region, lineNumber, lineStr):
		self.uid = int(uid)
		self.name = str(name)
		
		self.regionA = region.a
		self.regionB = region.b

		self.filePath = str(filePath)
		self.projectPath = str(projectPath)
		self.lineStr = str(lineStr)
		self.lineNumber = int(lineNumber)

	def getName(self):
		return self.name

	def getUid(self):
		return self.uid

	def getRegion(self):
		return sublime.Region(self.regionA, self.regionB)

	def getFilePath(self):
		return self.filePath

	def getProjectPath(self):
		return self.projectPath

	def getLineNumber(self):
		return self.lineNumber

	def getLineStr(self):
		return self.lineStr

	

	def setLineStr(self, newLineStr):
		self.lineStr = newLineStr

	def setRegion(self, region):
		self.region = region

class SublimeBookmarkCommand(sublime_plugin.WindowCommand):
	def __init__(self, window):
		global BOOKMARKS

		self.window = window
		assert self.window is not None

		BOOKMARKS = []
		self.thread = None
		self.uid = 0
		#bookmark that represents the file from which the panel was activated
		self.reverftBookmark = None

		currentDir = os.path.dirname(sublime.packages_path())
		self.SAVE_PATH = currentDir + '/sublimeBookmarks.pickle'
		Log(currentDir)

		self.optSelectorJob = None
		self.inputPanelJob = None

		self._Load()
		


	def run(self, type):
		global SHOW_ALL_BOOKMARKS

		if type == "add":
			self._addBookmark()

		elif type == "goto":
			self._gotoBookmark()

		elif type == "remove":
			self._removeBookmark()

		elif type == "show_all_bookmarks":
			SHOW_ALL_BOOKMARKS = True
			self._Save()
			self._updateMarks()

		elif type == "show_project_bookmarks":
			SHOW_ALL_BOOKMARKS = False
			self._Save()
			self._updateMarks()

		elif type == "remove_all":
			self._removeAllBookmarks()

		elif type == "mark_buffer":
			self._updateMarks()

		elif type == "move_bookmarks":
			self._MoveBookmarks();



	#event handlers----------------------------
	def _addBookmark(self):
		Log ("add")

		window = self.window
		view = window.active_view()
		region = getCurrentLineRegion(view)

		#copy whatever is on the line for the bookmark name
		initialText = view.substr(region).strip()


		self.inputPanelJob  = OptionsInput(self.window, "Add Bookmark", initialText, self._AddBookmarkCallback, None)
		self.inputPanelJob.run()

	def _gotoBookmark(self):
		window = self.window
		
		#create a list of acceptable bookmarks based on settings
		bookmarkItems = createBookmarkPanelItems(window, BOOKMARKS, SHOW_ALL_BOOKMARKS)

		#if no bookmarks are acceptable, don't show bookmarks
		if len(bookmarkItems) == 0:
			return

		#create a selection panel and launch it
		self.optSelectorJob = OptionsSelector(window, bookmarkItems, self._GotoDoneCallback, self._AutoMoveToBookmarkCallback)
		self.optSelectorJob.run()


	def _removeBookmark(self):

		window = self.window

		#create a revert bookmark to go back if the user cancels
		self.revertBookmark = self._createRevertBookmark(window.active_view())
		
		#create a list of acceptable bookmarks based on settings
		bookmarkItems = createBookmarkPanelItems(window, BOOKMARKS, SHOW_ALL_BOOKMARKS)

		#if no bookmarks are acceptable, don't show bookmarks
		if len(bookmarkItems) == 0:
			return

		#create a selection panel and launch it
		self.optSelectorJob = OptionsSelector(window, bookmarkItems, self._RemoveDoneCallback, self._AutoMoveToBookmarkCallback)
		self.optSelectorJob.run()


	def _removeAllBookmarks(self):
		window = self.window
		view = window.active_view()
		filePath = view.file_name()

		global BOOKMARKS
		global ERASED_BOOKMARKS

		for bookmark in BOOKMARKS:
			#store erased bookmarks for delayed removal
			ERASED_BOOKMARKS.append(copy(bookmark))
			#unmark all bookmarks that are currently visible for immediate feedback
			if bookmark.getFilePath() == filePath:
				unmarkBuffer(view, bookmark)

		#yep. nuke em
		del BOOKMARKS
		BOOKMARKS = []	

		self._updateMarks()
		#save to eternal storage
		self._Save()

	def _updateMarks(self):
		Log ("MARKING BUFFER")

		window = self.window
		view = window.active_view()
		
		if view is None:
			return
		filePath = view.file_name()
		
		#mark all bookmarks that are visible
		for bookmark in BOOKMARKS:
			shouldShow = shouldShowBookmark(bookmark, window, SHOW_ALL_BOOKMARKS)

			if bookmark.getFilePath() == filePath and shouldShow:
				markBuffer(view, bookmark)
			else:
				unmarkBuffer(view, bookmark)
				
		#unmark all erased bookmarks
		for bookmark in ERASED_BOOKMARKS:
			if bookmark.getFilePath() == filePath:
				unmarkBuffer(view, bookmark)

	def _MoveBookmarks(self):
		
		
		window = self.window
		view = window.active_view()

		if view is None:
			return

		filePath = view.file_name()
		
		global BOOKMARKS

		for bookmark in BOOKMARKS:
			#this bookmark (might) have been changed. We're on a thread anyway so update it.
			if bookmark.getFilePath() == filePath:
				uid = bookmark.getUid()
				#load the new region and set the bookmark's region again
				regions = view.get_regions(str(uid))

				#there is no region in the view
				assert (len(regions) != 0)
					
				#keep the new region on the *WHOLE* line
				newRegion = view.line(regions[0])
				newLineStr = view.substr(newRegion) 

				print newLineStr

				assert newRegion is not None
				bookmark.setRegion(newRegion)
				bookmark.setLineStr(newLineStr)

				#re-mark the buffer. This automagically clears the previous mark
				markBuffer(view, bookmark)
				
	#callbacks---------------------------------------------------
	def _AddBookmarkCallback(self, name):
		window = self.window
		view = window.active_view()
		assert view is not None

		
		filePath = view.file_name()

		#figure out the project path
		#HACK! projectPath = window.project_file_name()
		projectPath = ""
		if projectPath is None or projectPath is "":
			projectPath = NO_PROJECT

		#set the uID and increment it
		uID = self.uid
		self.uid = self.uid + 1

		#get region and line data
		region = getCurrentLineRegion(view)
		lineStr = view.substr(region)
		lineNumber = view.rowcol(view.sel()[0].begin())[0]


		Log ("CREATING ADD BOOKMARK")
		#create a bookmark and add it to the global list
		global BOOKMARKS

		bookmark = Bookmark(uID, name, filePath, projectPath, region, lineNumber, lineStr)
		BOOKMARKS.append(bookmark)

		markBuffer(view, bookmark)
		
		#File IO Here!--------------------
		self._Save()

	#display highlighted bookmark
	def _AutoMoveToBookmarkCallback(self, index):
		assert index < len(BOOKMARKS)
		bookmark = BOOKMARKS[index]
		assert bookmark is not None

		#goto highlighted bookmark
		gotoBookmark(bookmark, self.window)
		self._updateMarks()
	

	#if the user canceled, go back to the original file
	def _GotoDoneCallback(self, index):
		#if we started from a blank window, self.revertBookmark CAN be None
		if index == -1 and self.revertBookmark is not None:
			gotoBookmark(self.revertBookmark, self.window)
			self.revertBookmark = None
			return

		assert index < len(BOOKMARKS)
		bookmark = BOOKMARKS[index]
		assert bookmark is not None

		gotoBookmark(bookmark, self.window)
		self._updateMarks()
		
		self.revertBookmark = None
		


	#remove the selected bookmark or go back if user canceled
	def _RemoveDoneCallback(self, index):
		self._updateMarks()

		#if user canceled, do nothing
		if index != -1:

			global BOOKMARKS
			global ERASED_BOOKMARKS

			assert index < len(BOOKMARKS)

			#remove the mark from the bookmark
			window = self.window
			bookmark = BOOKMARKS[index]
			assert bookmark is not None

			#add to list of erased bookmarks
			ERASED_BOOKMARKS.append(copy(bookmark))
			del BOOKMARKS[index]
		
		#remark buffer
		self._updateMarks()

		#File IO Here!--------------------
		self._Save()


	#Save-Load----------------------------------------------------------------
	def _Load(self):
		global BOOKMARKS
		global SHOW_ALL_BOOKMARKS

		
		Log("LOADING BOOKMARKS")
		try:
			savefile = open(self.SAVE_PATH, "rb")

			SHOW_ALL_BOOKMARKS = load(savefile)
			self.uid = load(savefile)
			BOOKMARKS = load(savefile)
			
		except (OSError, IOError, UnpicklingError, EOFError) as e:
			print (e)
			print("\nUNABLE TO LOAD BOOKMARKS. NUKING LOAD FILE")
			#clear the load file :]
			open(self.SAVE_PATH, "wb").close()
			#if you can't load, try and save a "default" state
			self._Save()
		
	def _Save(self):
		global BOOKMARKS
		global SHOW_ALL_BOOKMARKS

		Log("SAVING BOOKMARKS")


		try:
			savefile = open(self.SAVE_PATH, "wb")

			dump(SHOW_ALL_BOOKMARKS, savefile)
			dump(self.uid, savefile)
			dump(BOOKMARKS, savefile)

			savefile.close()
		except (OSError, IOError, PicklingError) as e:
			print (e)
			print("\nUNABLE TO SAVE BOOKMARKS. PLEASE CONTACT DEV")
