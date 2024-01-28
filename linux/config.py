#!/bin/python3
'''
Provides an interactive menu system for the installation of various options. This
is primarily for new system installations to quickly get to a runnable state for 
various feature options and their dependencies. The options are generated from a
json file passed from the calling shell command.
'''

import copy
import json
import subprocess
import sys
from enum import Enum

import ansi

gl_install = f"{ansi.lt_green_fg}\u2192{ansi.off}"
gl_depinstall = f"{ansi.lt_yellow_fg}\u21aa{ansi.off}"
gl_uninstall = f"{ansi.lt_red_fg}\u2190{ansi.off}"
gl_detected = f"{ansi.lt_blue_fg}\u2713{ansi.off}"
gl_undetected = f"{ansi.dk_red_fg}\u26cc{ansi.off}"


def ensure_list(e):
    '''
    Returns a list containing e, if e is not already a list.
    '''
    return e if isinstance(e, list) else [e]


class Action(Enum):
    '''Actions user can select for options'''
    NONE = 0
    INSTALL = 1
    UNINSTALL = 2


class InstallStep:
    '''
    An installation step for a particular option.
    '''
    # pylint: disable=too-few-public-methods
    def __init__(self, json_object):
        self.detect_cmd = ""
        if "did" in json_object:
            self.detect_cmd = json_object["did"]
        self.install_cmd = ""
        if "do" in json_object:
            self.install_cmd = ensure_list(json_object["do"])
        self.uninstall_cmd = ""
        if "undo" in json_object:
            self.uninstall_cmd = ensure_list(json_object["undo"])
        self.detected = False

    def detect(self, vars_prefix):
        '''
        Runs the string value of self.detect_cmd as a shell command. Sets 
        self.detected if the command is successful (returns zero).

        Parameters:
        - vars_prefix (dict of Str->Str): key-value pairs of shell variables
        to prepend to the command, like:
        CS_FONTDIR=~/.local/share/fonts/mononoki-nerd CS_TMPFILE=/tmp/mononoki.zip [cmd]...
        '''
        res = subprocess.run(vars_prefix + self.detect_cmd, shell=True,
                             capture_output=True, check=False)
        self.detected = res.returncode == 0

def sort_vars(vardefs):
    '''
    Sort the dict in such a way as no key appears after its use in a previous value.
    Ensures that shell variables are defined before they are used in subsequent variables.

    Parameters:
    - vardefs (dict of Str->Str): variable definitions loaded from the json file.
    '''
    sorted_keys = []
    i = 0
    keys = list(vardefs.keys())
    while i < len(vardefs):
        key = keys[i]
        for j, skk in enumerate(sorted_keys):
            var = vardefs[skk]
            if key in var:
                sorted_keys.insert(j, key)
                break
        else:
            sorted_keys.append(key)
        i += 1
    return {k: vardefs[k] for k in sorted_keys}


class Option:
    '''
    A particular top-level installable feature.
    '''
    # pylint: disable=too-many-instance-attributes
    def __init__(self, name, json_obj):
        self.name = name
        self.vars = []
        self.vars_prefix = ''
        if "vars" in json_obj:
            self.vars = sort_vars(json_obj["vars"])
            self.vars_prefix = ' '.join(
                f'{name}={value}' for name, value in self.vars.items()) + ' '

        self.depends = []
        if "depends" in json_obj:
            self.depends = ensure_list(json_obj["depends"])

        self.install_steps = []
        if "install" in json_obj:
            install_steps = ensure_list(json_obj["install"])
            self.install_steps = [InstallStep(step) for step in install_steps]

        self.all_detected = False
        self.any_detected = False
        self.all_deps_detected = False
        self.action = Action.NONE
        self.is_dep_install = False

    def detect(self):
        '''
        Runs detection steps to determine the install status of each install step for this option.
        '''
        for inst in self.install_steps:
            inst.detect(self.vars_prefix)
        self.any_detected = (
            any((inst.detected for inst in self.install_steps))
            if len(self.install_steps) > 0
            else True
        )
        self.all_detected = (
            all((inst.detected for inst in self.install_steps))
            if len(self.install_steps) > 0
            else True
        )

    def select(self):
        '''
        Sets the appropriate action state for this option, based on detected installation state.
        '''
        if self.action == Action.NONE:
            if not self.all_detected or not self.all_deps_detected:
                self.action = Action.INSTALL
            elif self.any_detected:
                self.action = Action.UNINSTALL
        elif self.action == Action.INSTALL:
            if (
                self.any_detected and not self.all_detected
            ) or not self.all_deps_detected:
                self.action = Action.UNINSTALL
            else:
                self.action = Action.NONE
        elif self.action == Action.UNINSTALL:
            self.action = Action.NONE


class Config:
    '''
    Manages overall installation options.
    '''
    def __init__(self, json_path):
        self.options = {}
        with open(json_path, "r", encoding='UTF-8') as file:
            data = json.load(file)
            for k, v in data.items():
                self.options[k] = Option(k, v)

    def detect(self):
        '''
        Determines the installation status of each option.
        '''
        for opt in self.options.values():
            opt.detect()

        for key, opt in self.options.items():
            opt.all_deps_detected = not self._any_deps_fail(key)

    def _any_deps_fail(self, key):
        opt = self.options[key]
        fail = False
        for dep in opt.depends:
            depopt = self.options[dep]
            if not depopt.all_detected:
                fail = True
            else:
                fail = fail or self._any_deps_fail(dep)
        return fail

    def resolve_dep_installs(self):
        '''
        For any option to be installed, marks the dependency options that
        are not already fully installed.
        '''
        for opt in self.options.values():
            opt.is_dep_install = False

        def mark_dep_install(opt):
            if not opt.all_detected or not opt.all_deps_detected:
                opt.is_dep_install = True
                for dep in opt.depends:
                    mark_dep_install(self.options[dep])

        for opt in self.options.values():
            if opt.action == Action.INSTALL:
                mark_dep_install(opt)

    def select(self, idx):
        '''
        Selects an option from the presented list of options in the menu, updating
        its proposed action state.

        Parameters:
        - idx: 0-based index of the option selected.
        '''
        key = list(self.options.keys())[int(idx)]
        self.options[key].select()
        self.resolve_dep_installs()

    def do_actions(self):
        '''
        For each option marked with an option, performs the action to install or
        uninstall it. All installs happen first, and in dependency order; then
        all uninstalls happen.
        '''
        installs = [
            k
            for k, v in self.options.items()
            if v.action == Action.INSTALL or v.is_dep_install
        ]
        uninstalls = [
            k
            for k, v in self.options.items()
            if v.action == Action.UNINSTALL and k not in installs
        ]

        # make a sorted list of all install deps (even ones that are complete);
        # then remove what we don't need
        deps = copy.deepcopy(installs)
        i = 0
        while i < len(deps):
            dep = deps[i]
            for subdep in self.options[dep].depends:
                if subdep in deps:
                    di = deps.index(subdep)
                    if di < i:
                        del deps[di]
                        deps.append(subdep)
                        i -= 1
                else:
                    deps.append(subdep)
            i += 1
        i = 0
        while i < len(deps):
            dep = deps[i]
            if dep not in installs:
                del deps[i]
                i -= 1
            i += 1

        installs = deps

        for inst in installs:
            self._install(inst)

        for uninst in uninstalls:
            self._uninstall(uninst)

    def _install(self, key):
        '''
        Installs a given option. Dependencies are determined and installed separately.

        Parameters:
        - key (Str): The name of the option as appears in the menu / json.
        '''
        opt = self.options[key]
        break_outer = False
        for i, step in enumerate(opt.install_steps):
            if not step.detected:
                for ci, cmd in enumerate(step.install_cmd):
                    ret = subprocess.run(
                        opt.vars_prefix + cmd, shell=True, capture_output=True,
                        text=True, check=False)
                    if ret.returncode != 0:
                        print(
                            f"{ansi.lt_red_fg}Error performing install step "
                            f"{ansi.dk_white_fg}{i}.{ci}:'{cmd}'"
                            f"{ansi.lt_red_fg}. Aborting option install.{ansi.off}"
                        )
                        print(f"{ret.stderr}")
                        break_outer = True
                        break
            if break_outer:
                break
        opt.action = Action.NONE
        opt.is_dep_install = False

    def _uninstall(self, key):
        '''
        Unnstalls a given option. Dependencies are strictly not considered, so if this option
        is a dependency of something else, it can break. User will see this indicated in the menu.

        Parameters:
        - key (Str): The name of the option as appears in the menu / json.
        '''
        opt = self.options[key]
        any_error = False
        for i, step in enumerate(reversed(opt.install_steps)):
            if step.detected:
                for ci, cmd in enumerate(step.uninstall_cmd):
                    ret = subprocess.run(opt.vars_prefix + cmd, shell=True,
                                         capture_output=False, check=False)
                    if ret.returncode != 0:
                        print(
                            f"{ansi.lt_red_fg}Error performing uninstall step "
                            f"{ansi.dk_white_fg}{i}.{ci}: '{cmd}'"
                            f"{ansi.lt_red_fg}. Continuing uninstall anyway.{ansi.off}"
                        )
                        any_error = True
                        # we break out of this list of commands, but continue with the uninstall
                        break
        if not any_error:
            opt.action = Action.NONE

    def print_menu(self):
        '''
        Prints the menu of options to the user, with indicators of install state and
        passproposed actions.
        '''
        print(
            f"{ansi.lt_white_fg}Install options: {gl_install} selected for install; "
            f"{gl_depinstall} dependency install; {gl_uninstall} selected for uninstall; "
            f"{gl_detected} detected; {gl_undetected} not detected"
        )
        max_name = max((len(k) for k, _ in self.options.items()))
        max_comps = max((len(v.install_steps) for _, v in self.options.items()))

        idx = 1
        for k, v in self.options.items():
            ordinal = f"{ansi.lt_white_fg}{idx:2d}:{ansi.off}"
            action = " "
            if v.action == Action.INSTALL:
                action = gl_install
            elif v.is_dep_install:
                action = gl_depinstall
            elif v.action == Action.UNINSTALL:
                action = gl_uninstall
            name = f"{ansi.lt_white_fg}{k}{ansi.off}"
            name_pad = " " * (max_name - len(k))
            comps = f"{ansi.lt_black_fg}components:{ansi.off} " + "".join(
                [
                    gl_detected if inst.detected else gl_undetected
                    for inst in v.install_steps
                ]
            )
            comps_pad = " " * (max_comps - len(v.install_steps))
            deps = f"{ansi.lt_black_fg}dependencies:{ansi.off} " + (
                gl_detected if v.all_deps_detected else gl_undetected
            )
            menu_item = f"{ordinal} {action} {name} {name_pad} {comps} {comps_pad} {deps}{ansi.off}"
            print(menu_item)
            idx += 1
        print(f"{ansi.off}")

    def prompt(self):
        '''
        Prompts the user for actions to take.
        '''
        sel = input(
            "Make a numeric selection, c to proceed with current selections, or q to quit: "
        )
        if sel == "q":
            return False

        if sel == "c":
            self.do_actions()
            self.detect()
            return True

        if sel.isdigit():
            idx = int(sel) - 1
            if 0 <= idx < len(self.options):
                self.select(idx)
            else:
                print(
                    f"{ansi.lt_red_fg}Selection out of range. Try again, bucko.{ansi.off}"
                )

        else:
            print(f"{ansi.lt_red_fg}Unrecognized command.{ansi.off}")

        return True

    def loop(self):
        '''
        Main run loop for the menu.
        '''
        go = True
        while go:
            self.print_menu()
            go = self.prompt()


if __name__ == "__main__":
    config = Config(sys.argv[1])
    config.detect()
    config.loop()
