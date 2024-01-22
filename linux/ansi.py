off = '\033[0m'

dk_black_fg = '\033[30m'
dk_red_fg = '\033[31m'
dk_green_fg = '\033[32m'
dk_yellow_fg = '\033[33m'
dk_blue_fg = '\033[34m'
dk_magenta_fg = '\033[35m'
dk_cyan_fg = '\033[36m'
dk_white_fg = '\033[37m'

lt_black_fg = '\033[90m'
lt_red_fg = '\033[91m'
lt_green_fg = '\033[92m'
lt_yellow_fg = '\033[93m'
lt_blue_fg = '\033[94m'
lt_magenta_fg = '\033[95m'
lt_cyan_fg = '\033[96m'
lt_white_fg = '\033[97m'

dk_black_bg    = '\033[48;2;0;0;0m'
dk_red_bg      = '\033[48;2;15;0;0m'
dk_green_bg    = '\033[48;2;0;15;0m'
dk_yellow_bg   = '\033[48;2;15;15;0m'
dk_orange_bg   = '\033[48;2;15;7;0m'
dk_blue_bg     = '\033[48;2;0;0;15m'
dk_magenta_bg  = '\033[48;2;15;0;15m'
dk_cyan_bg     = '\033[48;2;0;15;15m'
dk_white_bg    = '\033[48;2;15;15;15m'


def rgb_fg(r, g, b):
    return f'\033[38;2;{r};{g};{b}m'

def rgb_bg(r, g, b):
    return f'\033[48;2;{r};{g};{b}m'


class Rgb:
    def __init__(self, r = 0, g = 0, b = 0):
        self.r = r
        self.g = g
        self.b = b

    def fg(self):
        return rgb_fg(int(self.r), int(self.g), int(self.b))

    def bg(self):
        return rgb_bg(int(self.r), int(self.g), int(self.b))

    def highlight(self):
        return Rgb(min(self.r * 2, 255), min(self.g * 2, 255), min(self.b * 2, 255))

    def dim(self):
        return Rgb(self.r / 2, self.g / 2, self.b / 2)


