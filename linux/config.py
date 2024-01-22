#!/bin/python3

import sys
import json
import ansi
import subprocess
import curses
import copy
from enum import Enum


gl_install = f"{ansi.lt_green_fg}\u2192{ansi.off}"
gl_depinstall = f"{ansi.lt_yellow_fg}\u21aa{ansi.off}"
gl_uninstall = f"{ansi.lt_red_fg}\u2190{ansi.off}"
gl_detected = f"{ansi.lt_blue_fg}\u2713{ansi.off}"
gl_undetected = f"{ansi.dk_red_fg}\u26cc{ansi.off}"


def ensureList(e): return e if isinstance(e, list) else [e]


class Action(Enum):
    NONE = 0
    INSTALL = 1
    UNINSTALL = 2


class InstallStep:
    def __init__(self, jsonObject):
        self.detectCmd = ''
        if 'did' in jsonObject:
            self.detectCmd = jsonObject['did']
        self.installCmd = ''
        if 'do' in jsonObject:
            self.installCmd = ensureList(jsonObject['do'])
        self.uninstallCmd = ''
        if 'undo' in jsonObject:
            self.uninstallCmd = ensureList(jsonObject['undo'])
        self.detected = False

    def detect(self):
        res = subprocess.run(self.detectCmd, shell=True, capture_output=True)
        self.detected = res.returncode == 0


class Option:
    def __init__(self, name, obj):
        self.name = name

        self.depends = []
        if 'depends' in obj:
            self.depends = ensureList(obj['depends'])

        self.installSteps = []
        if 'install' in obj:
            installSteps = ensureList(obj['install'])
            self.installSteps = [InstallStep(step) for step in installSteps]

        self.allDetected = False
        self.anyDetected = False
        self.allDependenciesDetected = False
        self.action = Action.NONE
        self.dependencyInstall = False

    def detect(self):
        for inst in self.installSteps:
            inst.detect()
        self.anyDetected = any([inst.detected for inst in self.installSteps]) if len(self.installSteps) > 0 else True
        self.allDetected = all([inst.detected for inst in self.installSteps]) if len(self.installSteps) > 0 else True

    def select(self):
        if self.action == Action.NONE:
            if not self.allDetected or not self.allDependenciesDetected:
                self.action = Action.INSTALL
            elif self.anyDetected:
                self.action = Action.UNINSTALL
        elif self.action == Action.INSTALL:
            if (self.anyDetected and not self.allDetected) or not self.allDependenciesDetected:
                self.action = Action.UNINSTALL
            else:
                self.action = Action.NONE
        elif self.action == Action.UNINSTALL:
            self.action = Action.NONE


class Config:
    def __init__(self, jsonPath):
        self.options = dict()
        with open(jsonPath, 'r') as file:
            data = json.load(file)
            for k, v in data.items():
                self.options[k] = Option(k, v)

    def detect(self):
        for opt in self.options.values():
            opt.detect()

        for key, opt in self.options.items():
            opt.allDependenciesDetected = not self.anyDependFail(key)

    def anyDependFail(self, key):
        opt = self.options[key]
        fail = False
        for dep in opt.depends:
            depopt = self.options[dep]
            if not depopt.allDetected:
                fail = True
            else:
                fail = fail or self.anyDependFail(dep)
        return fail

    def resolveDependencyInstalls(self):
        for opt in self.options.values():
            opt.dependencyInstall = False

        def markDepInstall(opt):
            if not opt.allDetected or not opt.allDependenciesDetected:
                opt.dependencyInstall = True
                for dep in opt.depends:
                    markDepInstall(self.options[dep])

        for opt in self.options.values():
            if opt.action == Action.INSTALL:
                markDepInstall(opt)

    def select(self, idx):
        key = list(self.options.keys())[int(idx)]
        self.options[key].select()
        self.resolveDependencyInstalls()

    def doActions(self):
        installs = [k for k, v in self.options.items() if v.action == Action.INSTALL or v.dependencyInstall]
        uninstalls = [k for k, v in self.options.items() if v.action == Action.UNINSTALL and k not in installs]

        # make a sorted list of all install deps (even ones that are complete); then remove what we don't need
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

        print (f'installs: {installs}')
        print (f'uninstalls: {uninstalls}')
        
        for inst in installs:
            self.install(inst)

        for uninst in uninstalls:
            self.uninstall(uninst)

    def install(self, key):
        opt = self.options[key]
        breakOuter = False
        for i, step in enumerate(opt.installSteps):
            if not step.detected:
                for ci, cmd in enumerate(step.installCmd):
                    ret = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    if ret.returncode != 0:
                        print (f"{ansi.lt_red_fg}Error performing install step {ansi.dk_white_fg}{i}.{ci}: '{cmd}'{ansi.lt_red_fg}. Aborting option install.{ansi.off}")
                        print (f"{ret.stderr}")
                        breakOuter = True
                        break
            if breakOuter:
                break
        opt.action = Action.NONE
        opt.dependencyInstall = False

    def uninstall(self, key):
        opt = self.options[key]
        anyError = False
        for i, step in enumerate(reversed(opt.installSteps)):
            if step.detected:
                for ci, cmd in enumerate(step.uninstallCmd):
                    ret = subprocess.run(cmd, shell=True, capture_output=False)
                    if ret.returncode != 0:
                        print (f"{ansi.lt_red_fg}Error performing uninstall step {ansi.dk_white_fg}{i}.{ci}: '{cmd}'{ansi.lt_red_fg}. Continuing uninstall anyway.{ansi.off}")
                        anyError = True
                        break   # we break out of this list of commands, but continue with the uninstall
        if not anyError:
            opt.action = Action.NONE

    def printMenu(self):
        print (f"{ansi.lt_white_fg}Install options: {gl_install} selected for install; {gl_depinstall} dependency install; {gl_uninstall} selected for uninstall; {gl_detected} detected; {gl_undetected} not detected")
        max_name = max([len(k) for k, _ in self.options.items()])
        max_comps = max([len(v.installSteps) for _, v in self.options.items()])
        
        idx = 1
        for k, v in self.options.items():
            ordinal  = f'{ansi.lt_white_fg}{idx:2d}:{ansi.off}'
            action   = ' '
            if v.action == Action.INSTALL:
                action = gl_install
            elif v.dependencyInstall:
                action = gl_depinstall
            elif v.action == Action.UNINSTALL:
                action = gl_uninstall
            name     = f'{ansi.lt_white_fg}{k}{ansi.off}'
            namePad  = ' ' * (max_name - len(k))
            comps    = (f'{ansi.lt_black_fg}components:{ansi.off} ' +
                       ''.join([gl_detected if inst.detected else gl_undetected for inst in v.installSteps]))
            compsPad = (' ' * (max_comps - len(v.installSteps)))
            deps     = (f'{ansi.lt_black_fg}dependencies:{ansi.off} ' +
                        (gl_detected if v.allDependenciesDetected else gl_undetected))
            menuItem = f'{ordinal} {action} {name} {namePad} {comps} {compsPad} {deps}{ansi.off}'
            print(menuItem)
            idx += 1
        print(f"{ansi.off}")

    def prompt(self):
        sel = input(f"Make a numeric selection, c to proceed with current selections, or q to quit: ")
        if sel == 'q':
            return False

        elif sel == 'c':
            self.doActions()
            self.detect()
            return True

        elif sel.isdigit():
            idx = int(sel) - 1
            if idx >= 0 and idx < len(self.options):
                self.select(idx)
            else:
                print(f"{ansi.lt_red_fg}Selection out of range. Try again, bucko.{ansi.off}")

        else:
            print(f"{ansi.lt_red_fg}Unrecognized command.{ansi.off}")

        return True

    def loop(self):
        go = True
        while (go):
            self.printMenu()
            go = self.prompt()

if __name__ == "__main__":
    config = Config(sys.argv[1])
    config.detect()
    config.loop()


