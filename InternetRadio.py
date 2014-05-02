#! /usr/bin/python

# UI wrapper for 'pianobar' client for Pandora, using Adafruit 16x2 LCD
# Pi Plate for Raspberry Pi.
# Written by Adafruit Industries.  MIT license.
#
# Required hardware includes any internet-connected Raspberry Pi
# system, any of the Adafruit 16x2 LCD w/Keypad Pi Plate varieties
# and either headphones or amplified speakers.
# Required software includes the Adafruit Raspberry Pi Python Code
# repository, pexpect library and pianobar.  A Pandora account is
# also necessary.
#
# Resources:
# http://www.adafruit.com/products/1109 RGB Positive 16x2 LCD + Keypad
# http://www.adafruit.com/products/1110 RGB Negative 16x2 LCD + Keypad
# http://www.adafruit.com/products/1115 Blue & White 16x2 LCD + Keypad

import atexit
import pickle
import socket
import time
import subprocess
import os
import linecache
#from plumbum.cmd import curl, grep
from Adafruit_I2C import Adafruit_I2C
from Adafruit_MCP230xx import Adafruit_MCP230XX
from Adafruit_CharLCDPlate import Adafruit_CharLCDPlate


# Constants:
RGB_LCD      = False # Set to 'True' if using color backlit LCD
HALT_ON_EXIT = True  # Set to 'True' to shut down system when exiting
MAX_FPS      = 6 if RGB_LCD else 4 # Limit screen refresh rate for legibility
VOL_MIN      =   0
VOL_MAX      = 100
VOL_BLOCKS   = float(VOL_MAX) / 7.0 # we've got 7 char blocks to display the volume bar
VOL_FRAGS    = VOL_BLOCKS / 5.0     # each char block has 5 fragments
VOL_DEFAULT  =  45
HOLD_TIME    = 3.0 # Time (seconds) to hold select button for shut down
PICKLEFILE   = '/home/pi/InternetRadio/laststate.p'

wundergroundAPIKey   = 'cb63d9447568ede4'
wundergroundStations = [['Lisboa', '38.728577,-9.132745']]#,
                     #   ['Hohenbrunn', '48.045271,11.701541'],
                     #   ['Deusmauer', '49.253409,11.625015'],
                     #   ['Boulder', '40.013121,-105.267848']]
lastWeatherUpdateTime = 0
weatherInfo = []

systemOptions = ['Shutdown', 'Reboot', 'WiFi Scan']

# Global state:
volCur       = VOL_MIN     # Current volume
volNew       = VOL_DEFAULT # 'Next' volume after interactions
volSpeed     = 1.0         # Speed of volume change (accelerates w/hold)
volSet       = False       # True if currently setting volume
paused       = False       # True if music is paused
menuSel      = False
staSel       = False       # True if selecting station
userSel      = False
weatherSel   = False
systemSel    = False
volTime      = 0           # Time of last volume button interaction
playMsgTime  = 0           # Time of last 'Playing' message display
staBtnTime   = 0           # Time of last button press on station menu
xTitle       = 16          # X position of song title (scrolling)
xInfo        = 16          # X position of artist/album (scrolling)
xStation     = 0           # X position of station (scrolling)
xTitleWrap   = 0
xInfoWrap    = 0
xStationWrap = 0
songTitle   = ''
songInfo    = ''
stationNum  = 0            # Station currently playing
stationNew  = 0            # Station currently highlighted in menu
menuNum     = 0
menuNew     = 0
userNum     = 0
userNew     = 0
weatherNew  = 0
systemNew   = 0
stationList = ['']
stationIDs  = ['']
currentInfoString = ''
userNames   = ['']
marqueeSpacing = ' ' * 8

# Char 7 gets reloaded for different modes.  These are the bitmaps:
charSevenBitmaps = [
  [0b10000, # Play (also selected station)
   0b11000,
   0b11100,
   0b11110,
   0b11100,
   0b11000,
   0b10000,
   0b00000],
  [0b11011, # Pause
   0b11011,
   0b11011,
   0b11011,
   0b11011,
   0b11011,
   0b11011,
   0b00000],
  [0b00000, # Next Track
   0b10100,
   0b11010,
   0b11101,
   0b11010,
   0b10100,
   0b00000,
   0b00000],
  [0b00000, # Previous Track
   0b00101,
   0b01011,
   0b10111,
   0b01011,
   0b00101,
   0b00000,
   0b00000]]

# these are saved in the standard directory /var/lib/mpd/playlists/
userFiles = ['/home/pi/InternetRadio/wifi_stations_Andreas.csv',
             '/home/pi/InternetRadio/wifi_stations_Melli.csv',
             '/home/pi/InternetRadio/wifi_stations_Anna.csv',
             '/home/pi/InternetRadio/wifi_stations_News.csv']

mainMenu  = ['Pause/Play',
             'Radio Stations',
             'Users',
             'Weather Info',
             'System Settings']

mpc_stop   = ['mpc', 'stop']
mpc_play   = ['mpc', 'play']
mpc_next   = ['mpc', 'next']
mpc_prev   = ['mpc', 'prev']
mpc_volup  = ['mpc', 'volume', '+5']
mpc_voldn  = ['mpc', 'volume', '-5']
mpc_vol    = ['mpc', 'volume']
mpc_add    = ['mpc', 'add']
mpc_clear  = ['mpc', 'clear']
mpc_file   = ['mpc', '-f', '%file%', 'current']
mpc_toggle = ['mpc', 'toggle']

mpc_current = ['mpc', 'current']
mpc_station = ['mpc', '-f', '%name%', 'current']
mpc_artist  = ['mpc', '-f', '%artist%', 'current']
mpc_album   = ['mpc', '-f', '%album%', 'current']
mpc_title   = ['mpc', '-f', '%title%', 'current']
mpc_time    = ['mpc', '-f', '%time%', 'current']

# --------------------------------------------------------------------------


# Exit handler tries to leave LCD in a nice state.
def cleanExit():
    if lcd is not None:
        time.sleep(0.5)
        lcd.backlight(lcd.OFF)
        lcd.clear()
        lcd.stop()
    run_cmd(mpc_stop)
    run_cmd(mpc_clear)


def shutdown():
    lcd.clear()
    if HALT_ON_EXIT:
        if RGB_LCD: lcd.backlight(lcd.YELLOW)
        lcd.message('Wait 30 seconds\nto unplug...')
        # Ramp down volume over 5 seconds while 'wait' message shows
        steps = int((volCur - VOL_MIN) + 0.5) + 1
        pause = 5.0 / steps
        for i in range(steps):
            run_cmd(mpc_voldn)
            time.sleep(pause)
        subprocess.call("sync")
        cleanExit()
        subprocess.call(["shutdown", "-h", "now"])
    else:
        exit(0)


def reboot():
    lcd.clear()
    if HALT_ON_EXIT:
        if RGB_LCD: lcd.backlight(lcd.YELLOW)
        lcd.message('Do not unplug,\nsystem reboots!')
        # Ramp down volume over 5 seconds while 'wait' message shows
        steps = int((volCur - VOL_MIN) + 0.5) + 1
        pause = 5.0 / steps
        for i in range(steps):
            run_cmd(mpc_voldn)
            time.sleep(pause)
        subprocess.call("sync") # write any outstanding buffers to disk
        subprocess.call(["reboot"])
    else:
        exit(0)


def wirelessInitialize():
    lcd.clear()
    if RGB_LCD: lcd.backlight(lcd.YELLOW)
    lcd.message('Re-initializing\nWiFi')
    # Ramp down volume over 5 seconds while 'wait' message shows
    steps = int((volCur - VOL_MIN) + 0.5) + 1
    pause = 5.0 / steps
    for i in range(steps):
        run_cmd(mpc_voldn)
        time.sleep(pause)
    subprocess.call(["ifdown", "--force", "wlan0"])
    subprocess.call(["ifup", "wlan0"])
    python = sys.executable
    os.execl(python, python, * sys.argv)



def updateWeatherInfo(lastTime):
    if time.time() - lastTime > 3600:
        lastTime = time.time()
        weatherInfo = []
        for wundergroundStation in wundergroundStations:
            wundergroundStationName = wundergroundStation[0]
            wundergroundStationLatLong = wundergroundStation[1]
            
            weatherFileName   = '/home/pi/InternetRadio/weather' + wundergroundStationName + '.txt'
            astroFileName     = '/home/pi/InternetRadio/astro' + wundergroundStationName + '.txt'
            weatherConditionsURL = 'http://api.wunderground.com/api/' + wundergroundAPIKey + '/conditions/q/' + wundergroundStationLatLong + '.json'
            weatherAstroURL      = 'http://api.wunderground.com/api/' + wundergroundAPIKey + '/astronomy/q/' + wundergroundStationLatLong + '.json'
            weatherConditionsCmd = curl ["-s", weatherConditionsURL] | grep ["-E", "full|temp_c|windchill_c|humidity|wind_dir|wind_kph|visibility|weather\""] > weatherFileName
            weatherconditions = "curl -s http://api.wunderground.com/api/" + wundergroundAPIKey + "/conditions/q/" + wundergroundStationLatLong + ".json | grep -E 'full|temp_c|windchill_c|humidity|wind_dir|wind_kph|visibility|weather\"' > " + weatherFileName
            weatherastro      = "curl -s http://api.wunderground.com/api/" + wundergroundAPIKey + "/astronomy/q/" + wundergroundStationLatLong + ".json | grep -E 'hour|minute' > " + astroFileName
            weatherconditions = weatherconditions.split(' ')
            weatherastro      = weatherastro.split(' ')
            subprocess.call(weatherconditions)
            subprocess.call(weatherastro)

            w_location = linecache.getline(weatherFileName, 1).split("\"")[3] # Location
            w_conditions = linecache.getline(weatherFileName, 3).split("\"")[3] # Weather Conditions
            w_acttemp = linecache.getline(weatherFileName, 4).split("\"")[2][1:-2] + "C" # Actual Temp
            w_humidty = linecache.getline(weatherFileName, 5).split("\"")[3] # Humidity
            w_wind = linecache.getline(weatherFileName, 6).split("\"")[3] + " @ " + linecache.getline(weatherFileName, 7).split("\"")[2][1:-2] + "km/h" # Wind Dir and Wind Speed in kph
            w_windchill = linecache.getline(weatherFileName, 8).split("\"")[3] + "C (Windchill)" # Windchill
            w_vis = linecache.getline(weatherFileName, 10).split("\"")[3] + "km Visibiltiy"# Visibility
          
            w_astro_sunrise = linecache.getline(astroFileName, 3).split("\"")[3] + ":" + linecache.getline(astroFileName, 4).split("\"")[3]
            w_astro_sunset = linecache.getline(astroFileName, 5).split("\"")[3] + ":" + linecache.getline(astroFileName, 6).split("\"")[3]

            weatherStr = w_location + ": " + w_conditions + " " + w_acttemp + " " + w_humidty + " " + w_wind + " Sunrise " + w_astro_sunrise + " Sunset " + w_astro_sunset
            weatherInfo.append(weatherStr)
    return lastTime


def run_cmd(cmd):
    p = subprocess.Popen(cmd, shell=False, stdout=subprocess.PIPE)
    output = p.communicate()[0]
    return output.strip(' \t\n\r')


# Draws song title or artist/album marquee at given position.
# Returns new position to avoid global uglies.
def marquee(s, x, y, xWrap):
    lcd.setCursor(0, y)
    if x > 0: # Initially scrolls in from right edge
        lcd.message(' ' * x + s[0:16-x])
    else:     # Then scrolls w/wrap indefinitely
        if len(s) > 16:
            lcd.message(s[-x:16-x])
            if x < xWrap:
                return 0
    return x - 1


def drawPlaying():
    lcd.createChar(7, charSevenBitmaps[0])
    lcd.setCursor(0, 1)
    lcd.message('\x07 Playing       ')
    return time.time()


def drawPaused():
    lcd.createChar(7, charSevenBitmaps[1])
    lcd.setCursor(0, 1)
    lcd.message('\x07 Paused        ')


def drawNextTrack():
    lcd.createChar(7, charSevenBitmaps[2])
    lcd.setCursor(0, 1)
    lcd.message('\x07Next station...')


def drawPrevTrack():
    lcd.createChar(7, charSevenBitmaps[3])
    lcd.setCursor(0, 1)
    lcd.message('\x07Prev station...')


# Draw station menu (overwrites fulls screen to facilitate scrolling)
def drawChoiceList(choiceList, choiceNew, listTop, xChoice, choiceBtnTime):
    last = len(choiceList)
    if last > 2:
        last = 2  # Limit stations displayed
    ret  = 0  # Default return value (for station scrolling)
    line = 0  # Line counter
    msg  = '' # Clear output string to start
    for s in choiceList[listTop:listTop+2]: # For each station...
        sLen = len(s) # Length of station name
        if (listTop + line) == choiceNew: # Selected station?
            msg += chr(7) # Show selection cursor
            if sLen > 15: # Is station name longer than line?
                if (time.time() - choiceBtnTime) < 0.5:
                    # Just show start of line for half a sec
                    s2 = s[0:15]
                else:
                    # After that, scrollinate
                    s2 = s + '   ' + s[0:15]
                    xChoiceWrap = -(sLen + 2)
                    s2 = s2[-xChoice:15-xChoice]
                    if xChoice > xChoiceWrap:
                        ret = xChoice - 1
            else: # Short station name - pad w/spaces if needed
                s2 = s[0:15]
                if sLen < 15: s2 += ' ' * (15 - sLen)
        else: # Not currently-selected station
            msg += ' '   # No cursor
            s2 = s[0:15] # Clip or pad name to 15 chars
            if sLen < 15: s2 += ' ' * (15 - sLen)
        msg  += s2 # Add station name to output message
        line += 1
        if line == last: break
        msg  += '\n' # Not last line - add newline
    lcd.setCursor(0, 0)
    lcd.message(msg)
    return ret


def getStations():
    lcd.clear()
    lcd.message('Retrieving\nstation list...')

    run_cmd(mpc_clear)

    file = open(userFiles[userNum], 'r');
    names     = []
    addresses = []
    # Parse each line
    for id, line in enumerate(file, start = 1):
        name, address = line.split(',')
        name = name.strip(' \t\n\r')
        address = address.strip(' \t\n\r')
        addresses.append(address)
        names.append(name)
        run_cmd(mpc_add + [address])
    file.close()
    return names, addresses

def mainMenuNavigation():
    global mainMenu, stationList, userNames, weatherInfo, systemOptions
    global menuNew, stationNew, userNew, weatherNew, systemNew
    global stationNum, userNum
    global cursorY, listTop, xStation, staBtnTime
    global paused, menuSel, staSel, userSel, weatherSel, systemSel
    menuNum = menuNew
    if mainMenu[menuNum] == "Pause/Play":
        paused = not paused
        run_cmd(mpc_toggle)
        if paused:
            drawPaused() #  Display play/pause change
        else:
            playMsgTime = drawPlaying()
        menuSel    = False
        staSel     = False
        userSel    = False
        weatherSel = False
        systemSel  = False
    elif mainMenu[menuNum] == "Radio Stations":
        if not staSel:
            staSel = True
            # Entering station selection menu.  Don't return to volume
            # select, regardless of outcome, just return to normal play.
            lcd.createChar(7, charSevenBitmaps[0])
            cursorY    = 0 # Cursor position on screen
            stationNew = 0 # Cursor position in list
            listTop    = 0 # Top of list on screen
            xStation   = 0 # X scrolling for long station names
            staBtnTime = time.time()
            drawChoiceList(stationList, stationNew, listTop, 0, staBtnTime)
        else:
            # Just exited station menu with selection - go play.
            stationNum = stationNew # Make menu selection permanent
            print('Selecting station: "{}"'.format(stationIDs[stationNum]))
            run_cmd(mpc_play + ["{0}".format(stationNum + 1)])
            paused = False
            menuSel    = False
            staSel     = False
            userSel    = False
            weatherSel = False
            systemSel  = False
    elif mainMenu[menuNum] == "Users":
        if not userSel:
            userSel = True
            lcd.createChar(7, charSevenBitmaps[0])
            cursorY     = 0 # Cursor position on screen
            userNew     = 0 # Cursor position in list
            listTop     = 0 # Top of list on screen
            xStation    = 0 # X scrolling for long station names
            staBtnTime = time.time()
            drawChoiceList(userNames, userNew, listTop, 0, staBtnTime)
        else:
            # Just exited user menu with selection - go play.
            userNum = userNew # Make menu selection permanent
            print('Selecting user: "{}"'.format(userNames[userNum]))
            run_cmd(mpc_stop)
            print(stationIDs[0])
            stationList, stationIDs = getStations()
            stationNum = 0
            print(stationIDs[stationNum])
            run_cmd(mpc_play)
            paused = False
            menuSel    = False
            staSel     = False
            userSel    = False
            weatherSel = False
            systemSel  = False
    elif mainMenu[menuNum] == 'Weather Info':
        if not weatherSel:
            weatherSel = True
            lcd.createChar(7, charSevenBitmaps[0])
            cursorY     = 0 # Cursor position on screen
            weatherNew  = 0 # Cursor position in list
            listTop     = 0 # Top of list on screen
            xStation    = 0 # X scrolling for long station names
            staBtnTime = time.time()
            drawChoiceList(weatherInfo, weatherNew, listTop, 0, staBtnTime)
        else: # we just want to go back into play mode
            paused = False
            menuSel    = False
            staSel     = False
            userSel    = False
            weatherSel = False
            systemSel  = False
    elif mainMenu[menuNum] == 'System Settings':
        if not systemSel:
            systemSel = True
            lcd.createChar(7, charSevenBitmaps[0])
            cursorY    = 0 # Cursor position on screen
            systemNew  = 0 # Cursor position in list
            listTop    = 0 # Top of list on screen
            xStation   = 0 # X scrolling for long station names
            staBtnTime = time.time()
            drawChoiceList(systemOptions, systemNew, listTop, 0, staBtnTime)
        else: # we just want to go back into play mode
            if systemOptions[systemNew] == 'Shutdown':
                shutdown()
            elif systemOptions[systemNew] == 'Reboot':
                reboot()
            elif systemOptions[systemNew] == 'WiFi Scan':
                resetWiFi()
            paused = False
            menuSel    = False
            staSel     = False
            userSel    = False
            weatherSel = False
            systemSel  = False

# --------------------------------------------------------------------------
# Initialization

atexit.register(cleanExit)

lcd = Adafruit_CharLCDPlate()
lcd.begin(16, 2)
lcd.clear()

# Create volume bargraph custom characters (chars 0-5):
for i in range(6):
    bitmap = []
    bits   = (255 << (5 - i)) & 0x1f
    for j in range(8):
        bitmap.append(bits)
    lcd.createChar(i, bitmap)

# Create up/down icon (char 6)
lcd.createChar(6,
  [0b00100,
   0b01110,
   0b11111,
   0b00000,
   0b00000,
   0b11111,
   0b01110,
   0b00100])

# By default, char 7 is loaded in 'pause' state
lcd.createChar(7, charSevenBitmaps[1])

# Get last-used volume and station name from pickle file
try:
    f = open(PICKLEFILE, 'rb')
    v = pickle.load(f)
    f.close()
    volNew         = v[0]
    defaultStation = v[1] 
    userNum        = v[2]
except:
    volString      = run_cmd(mpc_vol).split(':')[1].split('%')[0].strip(' \t\n\r')
    volNew         = int(volString)
    defaultStation = None
    userNum        = 0

# Populate user list
userNames = []
for uname in userFiles:
    uname = uname.split('_')[-1].split('.')[0]
    userNames.append(uname)

# populate weather information array
#lastWeatherUpdateTime = updateWeatherInfo(lastWeatherUpdateTime)

# Show IP address (if network is available).  System might be freshly
# booted and not have an address yet, so keep trying for a couple minutes
# before reporting failure.
t = time.time()
while True:
    if (time.time() - t) > 120:
        # No connection reached after 2 minutes
        if RGB_LCD: lcd.backlight(lcd.RED)
        lcd.message('Network is\nunreachable')
        time.sleep(30)
        exit(0)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 0))
        if RGB_LCD: lcd.backlight(lcd.GREEN)
        else:       lcd.backlight(lcd.ON)
        lcd.message('Informagic Radio\n@' + s.getsockname()[0])
        time.sleep(5)
        break         # Success -- let's hear some music!
    except:
        time.sleep(1) # Pause a moment, keep trying

stationList, stationIDs = getStations()
try:    # Use station name from last session
    stationNum = stationList.index(defaultStation)
except: # Use first station in list
    stationNum = 0
print('Selecting station ' + stationIDs[stationNum])
run_cmd(mpc_play + ["{0}".format(stationNum + 1)])


# --------------------------------------------------------------------------
# Main loop.  This is not quite a straight-up state machine; there's some
# persnickety 'nesting' and canceling among mode states, so instead a few
# global booleans take care of it rather than a mode variable.

if RGB_LCD:
    lcd.backlight(lcd.ON)
lastTime = 0

while True:
    s = run_cmd(mpc_current)
    if currentInfoString != s:
        currentInfoString = s

        songTitle  = ''
        songInfo   = ''
        xTitle     = 16
        xInfo      = 16
        xTitleWrap = 0
        xInfoWrap  = 0

        s = run_cmd(mpc_station)
        if len(s) != 0:
            print('Station: "{}"'.format(s))

        s = run_cmd(mpc_time)
        if len(s) != 0:
            print('\tTime: {}'.format(s))

        s = run_cmd(mpc_title).split('-')
        if len(s) >= 2 and len(s[1]) != 0:
            st = s[1].strip(' \t\n\r')
        else:
            st = '<No Song Title>'
        print('\tSong: "{}"'.format(st))
        st += marqueeSpacing
        n = len(st)
        xTitleWrap = -n + 2
        songTitle = st * (1 + (16 / n)) + st[0:16]

        if len(s) >= 1 and len(s[0]) != 0:
            artist = s[0].strip(' \t\n\r')
        else:
            artist = '<No Artist>'
        print('\tArtist: "{}"'.format(artist))
        si = artist

        if len(s) >= 3 and len(s[2]) != 0:
            album = s[2].strip(' \t\n\r')
            print('\tAlbum: "{}"'.format(album))
            si += ' [' + album + ']'
        si += marqueeSpacing
        n = len(si)
        xInfoWrap = -n + 2
        # 1+ copies + up to 15 chars for repeating scroll
        songInfo  = si * (2 + (16 / n)) + si[0:16]
    
        # Periodically dump state (volume and station name)
        # to pickle file so it's remembered between each run.
        try:
            f = open(PICKLEFILE, 'wb')
            pickle.dump([volCur, stationList[stationNum], userNum], f)
            f.close()
        except:
            pass

        # update weather info (there's an internal counter that allows an
        # update only each 60 minutes to keep within the limit of permitted
        # polls to wunderground.com)
        #lastWeatherUpdateTime = updateWeatherInfo(lastWeatherUpdateTime)
    

    # Poll all buttons once, avoids repeated I2C traffic for different cases
    b        = lcd.buttons()
    btnUp    = b & (1 << lcd.UP)
    btnDown  = b & (1 << lcd.DOWN)
    btnLeft  = b & (1 << lcd.LEFT)
    btnRight = b & (1 << lcd.RIGHT)
    btnSel   = b & (1 << lcd.SELECT)

    if btnSel:
        t = time.time()                        # Start time of button press
        while lcd.buttonPressed(lcd.SELECT):   # Wait for button release
            if (time.time() - t) >= HOLD_TIME: # Extended hold?
                shutdown()                     # We're outta here
        
        if not menuSel:    
            menuSel = True
            lcd.createChar(7, charSevenBitmaps[0])
            volSet      = False
            cursorY     = 0 # Cursor position on screen
            menuNew     = 0 # Cursor position in list
            listTop     = 0 # Top of list on screen
            xStation    = 0 # X scrolling for long station names
            staBtnTime  = time.time()
            drawChoiceList(mainMenu, menuNew, listTop, 0, staBtnTime)
        else:
            mainMenuNavigation()

    elif btnRight:
        if not menuSel and not staSel and not userSel and not weatherSel and not systemSel:
            drawNextTrack()
            stationNum = (stationNum + 1) % len(stationIDs)
            run_cmd(mpc_play + ["{0}".format(stationNum + 1)])
            lcd.setCursor(0, 0)
            shortStation = stationList[stationNum][0:15]
            shortStation = shortStation + ' ' * (16 - len(shortStation))
            lcd.message(shortStation)
            time.sleep(1.0)
        elif menuSel and not staSel and not userSel and not weatherSel and not systemSel:
            # if we are in menu mode, we want the right button to perform the "select" action
            # (just like the select button does it)
            mainMenuNavigation()

    elif btnLeft:
        if not menuSel and not staSel and not userSel and not weatherSel and not systemSel:
            drawPrevTrack()
            stationNum = (stationNum - 1) % len(stationIDs)
            run_cmd(mpc_play + ["{0}".format(stationNum + 1)])
            lcd.setCursor(0, 0)
            shortStation = stationList[stationNum][0:15]
            shortStation = shortStation + ' ' * (16 - len(shortStation))
            lcd.message(shortStation)
            time.sleep(1.0)
        elif menuSel:
            # if we are in menu mode, we want the left button to perform a "go back" action
            staSel     = False
            userSel    = False
            weatherSel = False
            systemSel  = False
            if not staSel and not userSel and not weatherSel and not systemSel:
                # go back to "play" mode
                paused = False
                menuSel = False
            if staSel or userSel or weatherSel or systemSel:
                # go back to the main menu by simulating a "select button" press
                lcd.createChar(7, charSevenBitmaps[0])
                volSet      = False
                cursorY     = 0 # Cursor position on screen
                menuNew     = 0 # Cursor position in list
                listTop     = 0 # Top of list on screen
                xStation    = 0 # X scrolling for long station names
                staBtnTime  = time.time()
                drawChoiceList(mainMenu, menuNew, listTop, 0, staBtnTime)

    elif btnUp or btnDown:
        if menuSel and not staSel and not userSel and not weatherSel and not systemSel:
            # Move up or down main menu
            if btnDown:
                if menuNew < (len(mainMenu) - 1):
                    menuNew += 1                 # Next menu item
                    if cursorY < 1: cursorY += 1 # Move cursor
                    else:           listTop += 1 # Y-scroll
                    xStation = 0                 # Reset X-scroll
            elif menuNew > 0:                    # btnUp implied
                    menuNew -= 1                 # Prev menu item
                    if cursorY > 0: cursorY -= 1 # Move cursor
                    else:           listTop -= 1 # Y-scroll
                    xStation = 0                 # Reset X-scroll
            staBtnTime = time.time()             # Reset button time
            xStation = drawChoiceList(mainMenu, menuNew, listTop, 0, staBtnTime)
        elif staSel:
            # Move up or down station menu
            if btnDown:
                if stationNew < (len(stationList) - 1):
                    stationNew += 1              # Next station
                    if cursorY < 1: cursorY += 1 # Move cursor
                    else:           listTop += 1 # Y-scroll
                    xStation = 0                 # Reset X-scroll
            elif stationNew > 0:                 # btnUp implied
                    stationNew -= 1              # Prev station
                    if cursorY > 0: cursorY -= 1 # Move cursor
                    else:           listTop -= 1 # Y-scroll
                    xStation = 0                 # Reset X-scroll
            staBtnTime = time.time()             # Reset button time
            xStation = drawChoiceList(stationList, stationNew, listTop, 0, staBtnTime)
        elif userSel:
            # Move up or down user menu
            if btnDown:
                if userNew < (len(userNames) - 1):
                    userNew += 1                 # Next user
                    if cursorY < 1: cursorY += 1 # Move cursor
                    else:           listTop += 1 # Y-scroll
                    xStation = 0                 # Reset X-scroll
            elif userNew > 0:                    # btnUp implied
                    userNew -= 1                 # Prev user
                    if cursorY > 0: cursorY -= 1 # Move cursor
                    else:           listTop -= 1 # Y-scroll
                    xStation = 0                 # Reset X-scroll
            staBtnTime = time.time()             # Reset button time
            xStation = drawChoiceList(userNames, userNew, listTop, 0, staBtnTime)
        elif weatherSel:
            # Move up or down weather menu
            if btnDown:
                if weatherNew < (len(weatherInfo) - 1):
                    weatherNew += 1              # Next user
                    if cursorY < 1: cursorY += 1 # Move cursor
                    else:           listTop += 1 # Y-scroll
                    xStation = 0                 # Reset X-scroll
            elif weatherNew > 0:                 # btnUp implied
                    weatherNew -= 1              # Prev user
                    if cursorY > 0: cursorY -= 1 # Move cursor
                    else:           listTop -= 1 # Y-scroll
                    xStation = 0                 # Reset X-scroll
            staBtnTime = time.time()             # Reset button time
            xStation = drawChoiceList(weatherInfo, weatherNew, listTop, 0, staBtnTime)
        elif systemSel:
            # Move up or down system config menu
            if btnDown:
                if systemNew < (len(systemOptions) - 1):
                    systemNew += 1               # Next user
                    if cursorY < 1: cursorY += 1 # Move cursor
                    else:           listTop += 1 # Y-scroll
                    xStation = 0                 # Reset X-scroll
            elif systemNew > 0:                  # btnUp implied
                    systemNew -= 1               # Prev user
                    if cursorY > 0: cursorY -= 1 # Move cursor
                    else:           listTop -= 1 # Y-scroll
                    xStation = 0                 # Reset X-scroll
            staBtnTime = time.time()             # Reset button time
            xStation = drawChoiceList(systemOptions, systemNew, listTop, 0, staBtnTime)
        else:
            if volSet is False:
                # Just entering volume-setting mode; init display
                lcd.setCursor(0, 1)
                volCurI = int((volCur - VOL_MIN) + 0.5)
                n = int(volCurI / VOL_BLOCKS)
                s = (chr(6) + ' Volume ' +
                        chr(5) * n +       # Solid brick(s)
                        chr(int( (volCurI % VOL_BLOCKS)/VOL_FRAGS )) + # Fractional brick 
                        chr(0) * (6 - n))  # Spaces
                lcd.message(s)
                volSet   = True
                volSpeed = 1.0
            # Volume-setting mode now active (or was already there);
            # act on button press.
            if btnUp:
                volNew = volCur + volSpeed
                if volNew > VOL_MAX:
                    volNew = VOL_MAX
            else:
                volNew = volCur - volSpeed
                if volNew < VOL_MIN:
                    volNew = VOL_MIN
            volTime   = time.time() # Time of last volume button press
            volSpeed *= 1.15        # Accelerate volume change
    else: # Other logic specific to unpressed buttons
        if staSel:
            # In station menu, X-scroll active station name if long
            if len(stationList[stationNew]) > 15:
                xStation = drawChoiceList(stationList, stationNew, listTop, xStation, staBtnTime)
        elif volSet:
            volSpeed = 1.0 # Buttons released = reset volume speed
            # If no interaction in 4 seconds, return to prior state.
            # Volume bar will be erased by subsequent operations.
            if (time.time() - volTime) >= 4:
                volSet = False
                if paused:
                    drawPaused()

    # Various 'always on' logic independent of buttons
    if not menuSel and not staSel and not userSel:
        # Play/pause/volume: draw upper line (song title)
        if songTitle is not None and len(songTitle) > 16:
            xTitle = marquee(songTitle, xTitle, 0, xTitleWrap)
        elif songTitle is not None:
            xTitle = 0
            songTitle = songTitle + ' ' * (16 - len(songTitle))
            lcd.setCursor(0, 0)
            lcd.message(songTitle)

        # Integerize current and new volume values
        volCurI = int((volCur - VOL_MIN) + 0.5)
        volNewI = int((volNew - VOL_MIN) + 0.5)
        volCur  = volNew
        # Issue change to mpc
        if volCurI != volNewI:
            run_cmd(mpc_vol + ["{0}".format(volNewI)])

        # Draw lower line (volume or artist/album info):
        if volSet:
            if volNewI != volCurI: # Draw only changes
                if(volNewI > volCurI):
                    x = int(volCurI / VOL_BLOCKS)
                    n = int(volNewI / VOL_BLOCKS) - x
                    s = chr(5) * n + chr(int( (volNewI % VOL_BLOCKS)/VOL_FRAGS ))
                    #print('n = ' + str(n) + 'half = ' + str(int(volNewI%(VOL_BLOCKS/float(5)))))
                else:
                    x = int(volNewI / VOL_BLOCKS)
                    n = int(volCurI / VOL_BLOCKS) - x
                    s = chr(int( (volNewI % VOL_BLOCKS)/VOL_FRAGS )) + chr(0) * n
                lcd.setCursor(x + 9, 1)
                lcd.message(s)
        elif paused == False:
            if (time.time() - playMsgTime) >= 3:
                # Display artist/album (rather than 'Playing')
                if songInfo is not None and len(songInfo) > 16:
                    xInfo = marquee(songInfo, xInfo, 1, xInfoWrap)
                elif songInfo is not None:
                    xInfo = 0
                    songInfo = songInfo + ' ' * (16 - len(songInfo))
                    lcd.setCursor(0, 1)
                    lcd.message(songInfo)


    # Throttle frame rate, keeps screen legible
    while True:
        t = time.time()
        if (t - lastTime) > (1.0 / MAX_FPS):
            break
    lastTime = t
