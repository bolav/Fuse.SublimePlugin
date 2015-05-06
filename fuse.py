import sublime, sublime_plugin, traceback
import json, threading, time, sys, os, time
from types import *
from Fuse.interop import *
from Fuse.cmd_parser import *
from Fuse.fuse_util import *
from Fuse.go_to_definition import *
from Fuse.build_results import *
from Fuse.output_view import *
from Fuse.build_output import *

apiVersion = (1,2)
remoteApiVersion = None
items = None
isUpdatingCache = False
autoCompleteEvent = None
closeEvent = None
interop = None
buildResults = None
outputView = OutputView()
buildOutput = BuildOutputView()
connectThread = None
useShortCompletion = False
wordAtCaret = ""

filterUXNamespaces = True

def Recv(msg):
	try:
		parsedRes = CmdParser.ParseCommand(msg)
		name = parsedRes[0]
		args = parsedRes[1]

		if name == "SetAPIVersion":
			HandleAPIVersion(args)
		if name == "SetCodeSuggestions":
			HandleCodeSuggestion(args)
		if name == "WriteToConsole":
			WriteToConsole(args)
		if name == "Error":
			Error(args)
		if name == "GoToDefinitionResponse":
			GoToDefinition(args)		
		if name == "BuildEventRaised":
			BuildEventRaised(args)
		if name == "NewBuild":
			global buildResults
			buildResults = BuildResults(sublime.active_window())		
	except:
		print(sys.exc_info()[0])

def HandleAPIVersion(args):
	versionString = args["Version"]
	tags = versionString.split(".")
	remoteApiVersion = (int(tags[0]), int(tags[1]))
	print(str.format("Remote Fuse plugin API version {0}.{1}",remoteApiVersion[0], remoteApiVersion[1]))
	print(str.format("Local Fuse plugin API version {0}.{1}",apiVersion[0], apiVersion[1]))
	if(remoteApiVersion[1]>1):
		if apiVersion[0] > remoteApiVersion[0] or apiVersion[1] > remoteApiVersion[1]:
			sublime.error_message(str.format("This plugin expects Fuse plugin API {0}.{1}\nAvailable plugin API is {2}.{3}\nMake sure you are running the latest version of Fuse.", apiVersion[0],apiVersion[1], remoteApiVersion[0], remoteApiVersion[1]))

def Error(cmd):
	print("Fuse - Error: " + cmd["ErrorString"])
	autoCompleteEvent.set()
	autoCompleteEvent.clear()

def WriteToConsole(args):
	typeOfConsole = args["Type"]
	if typeOfConsole == "DebugLog":
		outputView.Write(args["Text"])
	elif typeOfConsole == "BuildLog":
		buildOutput.Write(args["Text"])

def BuildEventRaised(cmd):
	buildResults.Add(cmd)

# Rebuild a sequence as a list of n-tuples
def Group(lst, n):
    return zip(*[lst[i::n] for i in range(n)]) 

def TrimType(typeDesc):
	return typeDesc.rpartition(".")[2]

# Parse a method or constructor into tab completion text, type hint and verbose hint
def ParseMethod(access, methodName, arguments, returntype, asCtor):

	args = arguments

	verboseHintText = " ".join(access)
	methodText = methodName+"("

	if asCtor:
		typeHint = "Class ("
	else:
		typeHint = "("

	count = 1
	for arg in args:
		if type(arg) is str:
			break

		if count>1:
			methodText += ", "
			typeHint += ", "

		argName = arg["Name"]
		
		if arg["IsOut"]:
			methodText += "out ${" + str(count) + ":" + argName + "}"
			typeHint += "out "
		else:
			methodText += "${" + str(count) + ":" + argName + "}"

		typeHint += TrimType(arg["ArgType"]) + " " + argName

		count += 1

	if asCtor:
		typeHint += ")"
	else:
		typeHint += "):" + TrimType(returntype)
	methodText += ")"

	return (methodText, typeHint, verboseHintText)

def HandleCodeSuggestion(cmd):
	suggestions = cmd["CodeSuggestions"]

	global items
	global isUpdatingCache
	global useShortCompletion
	global completionSyntax
	global doCompleteAttribs
	global wordAtCaret

	isUpdatingCache = cmd["IsUpdatingCache"]
	items = []

	try:
		# Determine which fields are enabled for completions
		# If remoteApiVersion hasn't been defined, base fields on that
		# Version no used to pick fields is determined from lowest minor version of local and remote

		minor = apiVersion[1]
		if remoteApiVersion != None:
			minor = min(apiVersion[1], remoteApiVersion[1])

		suggestedUXNameSpaces = []

		for suggestion in suggestions:

			outText = suggestionText = suggestion["Suggestion"]
			suggestionType = suggestion["Type"]
			hintText = "" # The right-column hint text

			if minor >= 1:

				if doCompleteAttribs and completionSyntax == "UX" and suggestionType == "Property":
					isNs = False
					hintText = suggestion["ReturnType"]
					if filterUXNamespaces and wordAtCaret != ":":
						colonIdx = suggestionText.find(":") + 1
						if colonIdx > 0:
							nsname = suggestionText[0:colonIdx]
							hinted = nsname in suggestedUXNameSpaces
							isNs = True
							if not hinted:
								suggestedUXNameSpaces.append(nsname)
								outText = nsname
								suggestionText = nsname[0:len(nsname)-1]
							else:
								continue

					if not isNs and (not useShortCompletion):
						suggestionText += '="${1}"'
				else:
					hintText = suggestion["ReturnType"]
					accessModifiers = suggestion["AccessModifiers"]
					fieldModifiers = suggestion["FieldModifiers"]
					arguments = suggestion["MethodArguments"]

					outText = suggestionText

					if suggestionType == "Method" or suggestionType == "Constructor":
						# Build sublime tab completion, type hint and verbose type hint
						parsedMethod = ParseMethod(accessModifiers, suggestionText, arguments, hintText, suggestionType == "Constructor")

						if not useShortCompletion:
							suggestionText = parsedMethod[0]
						hintText = parsedMethod[1]

					if suggestionType == "Field" or suggestionType == "Property":
						hintText = TrimType(hintText)


			if suggestion["PreText"] != "":
				suggestionText = suggestion["PreText"] + suggestion["PostText"]


			outText += "\t" + hintText
			if(outText.casefold().find(wordAtCaret.casefold()) > -1):
				items.append((outText, suggestionText))

	except:
		traceback.print_exc()

	autoCompleteEvent.set()
	autoCompleteEvent.clear()

def plugin_loaded():
	global items
	global autoCompleteEvent
	global closeEvent
	global interop
	global buildResults
	global completionSyntax
	global doCompleteAttribs

	completionSyntax = ""
	items = []
	autoCompleteEvent = threading.Event()
	closeEvent = threading.Event()
	interop = Interop(Recv, SendHandshake)
	buildResults = BuildResults(sublime.active_window())

	global connectThread
	connectThread = threading.Thread(target = TryConnect)
	connectThread.daemon = True
	connectThread.start()

	s = sublime.load_settings("Preferences.sublime-settings")
	if GetSetting("fuse_open_files_in_same_window"):
		s.set("open_files_in_new_window", False)
	else:
		s.set("open_files_in_new_window", True)

	doCompleteAttribs = GetSetting("fuse_ux_attrib_completion")

def plugin_unloaded():
	closeEvent.set()
	connectThread.join(1)

	global interop
	interop = None	

def TryConnect():	
	try:		
		while not closeEvent.is_set():
			if GetSetting("fuse_enabled") == True and not interop.IsConnected():
				interop.Connect()
				if interop.IsConnected():
					SendHandshake()				

			time.sleep(1)
	finally:
		interop.Disconnect()

def SendHandshake():
	interop.Send(json.dumps({"Command":"SetFeatures", "Arguments":
		{"Features":[{"Name":"CodeCompletion"}, 
		{"Name": "Console"}, 
		{"Name": "BuildEvent"},
		{"Name": "ShortcutFeature"}]}}))

class FuseEventListener(sublime_plugin.EventListener):

	def on_modified(self, view):
		global useShortCompletion
		global wordAtCaret
		caret = view.sel()[0].a
		vstr = view.substr(caret)
		wordAtCaret = view.substr(view.word(caret)).strip()

		if vstr == "(" or vstr == "=": 
			useShortCompletion = True
		else:
			useShortCompletion = False

	def RequestAutoComplete(self, view, syntaxName):

		fileName = view.file_name()
		text = view.substr(sublime.Region(0,view.size()))
		caret = view.sel()[0].a

		interop.Send(json.dumps({"Command":"RequestCodeCompletion", "Arguments":{
			"QueryId": 0,
			"Path": fileName, "Text": text, 
			"Type": syntaxName, "CaretPosition": GetRowCol(view, caret)}}))

	def on_query_completions(self, view, prefix, locations):
		global items
		global completionSyntax

		if GetSetting("fuse_completion") == False or not interop.IsConnected():
			return

		syntaxName = GetExtension(view.settings().get("syntax"))
		if not IsSupportedSyntax(syntaxName):
			return

		completionSyntax = syntaxName

		self.RequestAutoComplete(view, syntaxName)

		autoCompleteEvent.wait(0.2)
		
		data = (items, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)
		if len(items) == 0:
			if isUpdatingCache == True:
				return ([("Updating suggestion cache...", "_"), ("", "")], sublime.INHIBIT_WORD_COMPLETIONS)

			if GetSetting("fuse_if_no_completion_use_sublime") == False:				
				return ([("", "")], sublime.INHIBIT_WORD_COMPLETIONS)
			else:
				return

		items = []
		return data

class DisconnectCommand(sublime_plugin.ApplicationCommand):
	def run(self):
		interop.Disconnect()	

class ToggleBuildresCommand(sublime_plugin.ApplicationCommand):
	def run(self):	
		buildResults.ToggleShow()

class ToggleOutputviewCommand(sublime_plugin.ApplicationCommand):
	def run(self):
		outputView.ToggleShow()

class ToggleBuildoutputCommand(sublime_plugin.ApplicationCommand):
	def run(self):
		buildOutput.ToggleShow()

class GotoDefinitionCommand(sublime_plugin.TextCommand):
	def run(self, edit):		
		view = self.view

		syntaxName = GetExtension(view.settings().get("syntax"))		
		if not IsSupportedSyntax(syntaxName) or len(view.sel()) == 0:
			return

		text = view.substr(sublime.Region(0,view.size()))
		caret = view.sel()[0].a

		interop.Send(json.dumps({"Command": "GotoDefinition", "Arguments":{
			"Path": view.file_name(),
			"Text": text,
			"Type": syntaxName,
			"CaretPosition": GetRowCol(view, caret),
			"QueryId": 0}}))

class FuseBuildRunCommand(sublime_plugin.ApplicationCommand):
	def run(self):
		interop.Send(json.dumps({"Command": "BuildAndRun"}))

class FuseRecompileCommand(sublime_plugin.ApplicationCommand):
	def run(self):
		interop.Send(json.dumps({"Command": "Recompile"}))
