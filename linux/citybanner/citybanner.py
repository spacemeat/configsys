#!/usr/bin/python3

import random
import os
import shutil
import sys


halfBlockGlyph = str(chr(0x2584)) #"\xe2\x96\x84"
windowGlyphs   = [ '.',
                   '-',
                   '=',
                   '_',
                   chr(0x2500), # "\xe2\x94\x80",
                   chr(0x2501), # "\xe2\x94\x81",
                   chr(0x2502), # "\xe2\x94\x81",
                   chr(0x2503), # "\xe2\x94\x81",
                   chr(0x2504), # "\xe2\x94\x81",
                   chr(0x2505), # "\xe2\x94\x81",
                   chr(0x2506), # "\xe2\x94\x81",
                   chr(0x2507), # "\xe2\x94\x81",
                   chr(0x250e), # "\xe2\x94\x81",
                   chr(0x2512), # "\xe2\x94\x81",
                   chr(0x254c), # "\xe2\x94\x87",
                   chr(0x254d), # "\xe2\x94\x87",
                   chr(0x254e), # "\xe2\x94\x87",
                   chr(0x254f), # "\xe2\x94\x87",
                   chr(0x2574), # "\xe2\x94\x87",
                   chr(0x2578), # "\xe2\x94\x87",
                   chr(0x257a), # "\xe2\x94\x87",

                   chr(0x2596), # "\xe2\x96\x96",
                   chr(0x2597), # "\xe2\x96\x97",
                   chr(0x25aa), # "\xe2\x96\xaa",
                   chr(0x25ac), # "\xe2\x96\xac",
                   chr(0x25ae)  # "\xe2\x96\xae"
                  ]

class Color:
    def __init__(self, hr, sg, vb, rgb=False):
        if rgb:
            self.setRgb(hr, sg, vb)
        else:
            self.setHsv(hr, sg, vb)

    def setRgb(self, r, g, b):
        (self.r, self.g, self.b) = (r, g, b)
        (self.h, self.s, self.v) = Color.rgb2hsv(r, g, b)

    def setHsv(self, h, s, v):
        (self.h, self.s, self.v) = (h, s, v)
        (self.r, self.g, self.b) = Color.hsv2rgb(h, s, v)

    def toAnsiFg(self):
        return f'\033[38;2;{self.r};{self.g};{self.b}m'

    def toAnsiBg(self):
        return f'\033[48;2;{self.r};{self.g};{self.b}m'

    def __repr__(self):
        return f'r: {self.r}; g: {self.g}; b: {self.b}'

    @staticmethod
    def noAnsi():
        return f'\033[m'

    @staticmethod
    def rgb2hsv(r, g, b):
        pass

    @staticmethod
    def hsv2rgb(h, s, v):
        if s == 0:
            return (v, v, v)

        region = int(h / 43)
        r = (h - region * 43) * 6
        p = int(((255 -                       s) * v) / 256) % 256
        q = int(((255 - ((        r * s) / 256)) * v) / 256) % 256
        t = int(((255 - (((255 - r) * s) / 256)) * v) / 256) % 256

        return [(v, t, p),
                (q, v, p),
                (p, v, t),
                (p, q, v),
                (t, p, v),
                (v, p, q)][region]

    @staticmethod
    def lerp(c0, c1, factor):
        return Color(int(c1.h * factor + c0.h * (1.0 - factor)),
                     int(c1.s * factor + c0.s * (1.0 - factor)),
                     int(c1.v * factor + c0.v * (1.0 - factor)))

    @staticmethod
    def makeRandom():
        return Color(random.randrange(256),
                     random.randrange(256),
                     random.randrange(256))

class Texel:
    def __init__(self):
        pass

    def setFgColor(self, fgColor):
        self.fgColor = fgColor

    def setBgColor(self, bgColor):
        self.bgColor = bgColor

    def setChar(self, char):
        self.char = char


class Raster:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.texels = []
        for r in range(0, height):
            row = []
            self.texels.append(row)

            for c in range(0, width):
                row.append(Texel())


    def fillSky(self, colorTop, colorBottom):
        for r in range(0, self.height):
            skyColor0 = Color.lerp(colorTop, colorBottom, 
                (r * 2) / (self.height * 2 - 1))
            skyColor1 = Color.lerp(colorTop, colorBottom, 
                (r * 2 + 1) / (self.height * 2 - 1))
            for c in range(0, self.width):
                self.texels[r][c].setBgColor(skyColor0)
                self.texels[r][c].setFgColor(skyColor1)
                self.texels[r][c].setChar(halfBlockGlyph)


    def fillBuilding(self, colorWall, colorWindow, windowChar, x, width, height, lightOnProbability):
        startingTexelRow = int(self.height * 2 - height)
        startingRow = int((startingTexelRow + 1) / 2)

        #print (f'bldg: wall: {colorWall}; window: {colorWindow}; char: {windowChar}; x: {x}; width: {width}; height: {height}')
        # do the half-pixel roof
        if startingTexelRow % 2 == 1:
            for c in range(x, x + width):
                if c >= 0 and c < self.width:
                    self.texels[startingRow - 1][c].setFgColor(colorWall)
                    self.texels[startingRow - 1][c].setChar(halfBlockGlyph)

        for r in range(startingRow, self.height):
            for c in range(x, x + width):
                if c >= 0 and c < self.width:
                    wc = Color(0, 0, 0)
                    if random.random() < lightOnProbability:
                        wc = colorWindow

                    self.texels[r][c].setBgColor(colorWall)
                    self.texels[r][c].setFgColor(wc)
                    self.texels[r][c].setChar(windowChar)


    def renderRow(self, row):
        cbg = ''
        cfg = ''
        s = ''
        for c in range(0, self.width):
            bg = self.texels[row][c].bgColor.toAnsiBg()
            if bg != cbg:
                s += f'{bg}'
                cbg = bg
            fg = self.texels[row][c].fgColor.toAnsiFg()
            if fg != cfg:
                s += f'{fg}'
                cfg = fg
            s += self.texels[row][c].char
        s += f'{Color.noAnsi()}\n'
        return s


    def render(self):
        s = ''
        for r in range(0, self.height):
            s += self.renderRow(r)
        return s

    def __repr__(self):
        endl='\n'
        return f'width: {self.width}; {len(self.texels[0])}{endl}height: {self.height}; {len(self.texels)}{endl}'


class City:
    def __init__(self, width, height):
        self.raster = Raster(width, height)
        random.seed()
        numBuildings = random.randrange(width) + width << 1
        skyColor0 = Color.makeRandom()
        skyColor1 = Color.makeRandom()

        self.raster.fillSky(skyColor0, skyColor1)

        for b in range(0, numBuildings):
            bWidth = random.randrange(4) + 1
            bxStart = random.randrange(width + bWidth) - bWidth
            bxEnd = bxStart + bWidth
            bHeight = random.randrange(1, height * 2 - 2)

            bWall = Color(0, 0, random.randrange(int(skyColor0.v / 4 + 1)))
            bWindow = Color(43, random.randrange(100), 255 - skyColor0.v)

            self.raster.fillBuilding(bWall, bWindow, 
                windowGlyphs[random.randrange(len(windowGlyphs))], bxStart, bWidth, bHeight, (255 - skyColor0.v) / 256)

    def render(self):
        return self.raster.render()


cols = int(sys.argv[1]) if len(sys.argv) > 1 else -1
rows = int(sys.argv[2]) if len(sys.argv) > 2 else -1

if cols == -1 or rows == -1:
    (tcols, trows) = shutil.get_terminal_size()
    if cols == -1:
        cols = tcols
    if rows == -1:
        rows = min(trows, 8)

city = City(cols, rows)
print (city.render())


