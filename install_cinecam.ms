--------------------------------------------------------------------------------
-- Cinematic camera moves -- 3ds Max installer.
--
-- Run it once (Scripting > Run Script, or drag it into a viewport) and every
-- camera in the scene grows a "Cinematic move" rollout at the end of its Modify
-- panel. Cameras created afterwards get one as they are made, and cameras in
-- scenes opened afterwards get one on open.
--
-- Nothing here decides anything about a shot. It puts server/ on Python's path,
-- hands the rollout definition to Max, and registers the callbacks; the moves
-- themselves are in server/cinecam.py and have no idea a host exists.
--
-- To undo: delete cinecam_startup.ms from your user startup scripts folder (if
-- you chose to write one), and run
--     python.Execute "import cinecam_max; cinecam_max.disable_auto_attach()"
--------------------------------------------------------------------------------
(
	local silent = (globalVars.isGlobal #gCineCamSilent) and gCineCamSilent == true
	local src = getSourceFileName()

	if src == undefined then (
		messageBox "Run this from a file (Scripting > Run Script) rather than from the listener, so it can find the server folder next to itself." title:"Cinematic move"
	) else (

	local home = getFilenamePath src
	local serverDir = home + "server"
	local probe = serverDir + "\\cinecam_max.py"

	if not (doesFileExist probe) then (
		messageBox ("Cannot find:\n" + probe + "\n\nKeep install_cinecam.ms in the cinematic_cameras folder, beside server/.") title:"Cinematic move"
	) else (

	-- The rollout's buttons read this global to put server/ back on sys.path in
	-- a session where the installer has not run -- opening someone else's scene,
	-- most often. Forward slashes so the path survives being pasted into a
	-- Python string literal.
	global gCineCamHome = serverDir
	local pyDir = substituteString serverDir "\\" "/"

	local boot = ("import importlib, sys\n" +
		"p = \"" + pyDir + "\"\n" +
		"if p not in sys.path: sys.path.insert(0, p)\n" +
		"import cinecam, movespec, maxui\n" +
		"for _m in (cinecam, movespec, maxui): importlib.reload(_m)\n" +
		"import cinecam_max\n" +
		"importlib.reload(cinecam_max)\n" +
		"cinecam_max.enable_auto_attach()\n" +
		"_n = cinecam_max.install_on_all_cameras()\n" +
		"print('[cinecam] rollout added to %d camera(s)' % _n)\n")

	local ok = true
	try (python.Execute boot) catch (
		ok = false
		messageBox ("The Python side would not load.\n\n" + (getCurrentException()) +
			"\n\nCheck that this 3ds Max has pymxs and that server/ is readable.") title:"Cinematic move"
	)

	if ok do (
		format "[cinecam] installed from %\n" serverDir

		if not silent do (
			if (queryBox ("Cameras in this scene now have the rollout.\n\n" +
				"Load it automatically every time 3ds Max starts?\n\n" +
				"This writes cinecam_startup.ms into your user startup scripts folder. Delete that file to undo.")
				title:"Cinematic move") do (

				local dst = (getDir #userStartupScripts) + "\\cinecam_startup.ms"
				local f = try (createFile dst) catch (undefined)
				if f == undefined then (
					messageBox ("Could not write:\n" + dst) title:"Cinematic move"
				) else (
					format "-- Written by install_cinecam.ms. Delete this file to undo.\n" to:f
					format "global gCineCamSilent = true\n" to:f
					format "fileIn @\"%\"\n" src to:f
					close f
					messageBox ("Written:\n" + dst) title:"Cinematic move"
				)
			)
		)
	)

	))
)
