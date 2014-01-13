import sublime, sublime_plugin

class bookmarkWatcher(sublime_plugin.EventListener):
	def on_activated(self, view):
		pass
		sublime.active_window().run_command("sublime_bookmark", {"type": "mark_buffer" } )


	def on_modified(self, view):
		pass
		sublime.active_window().run_command("sublime_bookmark", {"type": "move_bookmarks" } ) 

	def on_selection_modified(self, view):
		pass
		sublime.active_window().run_command("sublime_bookmark", {"type": "move_bookmarks" } ) 
		
	def on_deactivated_async(self, view):
		pass
		
	def on_pre_save_async(self, view):
		pass
		#sublime.run_command("sublime_bookmark", {"type": "save_data" } )

