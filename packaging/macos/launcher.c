/*
 * Obscura.app/Contents/MacOS/Obscura — starts the bundled Python inside the app's own process so macOS shows
 * "Obscura" (with its icon) in the Dock, then runs `obscura.launcher`.
 *
 * Bundle layout:
 *   Contents/MacOS/Obscura                 this program
 *   Contents/Resources/runtime/            relocatable CPython 3.12 (python-build-standalone) + packages
 *   Contents/Resources/app/                obscura/, frontend/, scripts/
 *   Contents/Resources/models/             AI models (full installer only)
 *   Contents/Resources/tesseract/          OCR engine
 */
#include <Python.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void fail(const char *msg) {
    fprintf(stderr, "Obscura: %s\n", msg);
    exit(1);
}

int main(int argc, char *argv[]) {
    char exe[PATH_MAX], real[PATH_MAX], dir[PATH_MAX], res[PATH_MAX], resources[PATH_MAX];
    char home[PATH_MAX], app[PATH_MAX];
    uint32_t size = sizeof(exe);
    if (_NSGetExecutablePath(exe, &size) != 0 || !realpath(exe, real)) fail("cannot locate the application");
    strncpy(dir, real, sizeof(dir));
    snprintf(res, sizeof(res), "%s/../Resources", dirname(dir));
    if (!realpath(res, resources)) fail("application resources are missing — reinstall Obscura");
    snprintf(home, sizeof(home), "%s/runtime", resources);
    snprintf(app, sizeof(app), "%s/app", resources);

    setenv("OBSCURA_INSTALL_DIR", resources, 1);
    setenv("OBSCURA_LAUNCHER_EXE", real, 1);
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1);  /* never write into the signed bundle */
    if (chdir(app) != 0) fail("application files are missing — reinstall Obscura");

    PyStatus status;
    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    config.use_environment = 0;      /* ignore PYTHONPATH / PYTHONHOME of the user's shell */
    config.user_site_directory = 0;  /* never load packages from ~/.local */
    config.parse_argv = 0;
    status = PyConfig_SetBytesString(&config, &config.home, home);
    if (PyStatus_Exception(status)) goto error;
    /* run_module would derive sys.path[0] from argv[0] (Contents/MacOS); put the app folder there explicitly */
    setenv("OBSCURA_APP_DIR", app, 1);
    status = PyConfig_SetBytesString(&config, &config.run_command,
        "import os, sys\n"
        "sys.path.insert(0, os.environ['OBSCURA_APP_DIR'])\n"
        "from obscura.launcher import main\n"
        "raise SystemExit(main(sys.argv[1:]))\n");
    if (PyStatus_Exception(status)) goto error;

    /* drop the "-psn_…" process serial number older macOS versions pass to apps */
    char **args = calloc((size_t)argc + 1, sizeof(char *));
    int n = 0;
    for (int i = 0; i < argc; i++) {
        if (i > 0 && strncmp(argv[i], "-psn_", 5) == 0) continue;
        args[n++] = argv[i];
    }
    status = PyConfig_SetBytesArgv(&config, n, args);
    if (PyStatus_Exception(status)) goto error;

    status = Py_InitializeFromConfig(&config);
    if (PyStatus_Exception(status)) goto error;
    PyConfig_Clear(&config);
    return Py_RunMain();

error:
    PyConfig_Clear(&config);
    Py_ExitStatusException(status);
}
