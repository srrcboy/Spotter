#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Created on Sat Dec 15 21:14:43 2012
@author: <Ronny Eichler> ronny.eichler@gmail.com

Track position LEDs and sync signal from camera or video file.

Usage:
    spotterQt.py [--source SRC --outfile DST] [options]
    spotterQt.py -h | --help

Options:
    -h --help           Show this screen
    -f --fps FPS        Fps for camera and video
    -s --source SRC     Path to file or device ID [default: 0]
    -S --Serial         Serial port to uC [default: None]
    -o --outfile DST    Path to video out file [default: None]
    -d --dims DIMS      Frame size [default: 640x360]
    -D --DEBUG          Verbose output

To do:
    - destination file name may consist of tokens to automatically create,
      i.e., %date%now%iterator3$fixedstring
    - track low res, but store full resolution
    - can never overwrite a file

#Example:
    --source 0 --outfile test.avi --size=320x200 --fps=30

"""

__version__ = 0.50

NO_EXIT_CONFIRMATION = True
DIR_EXAMPLES = './media/vid'
DIR_TEMPLATES = './templates'
DIR_CONFIG = './lib/core/config'
DEFAULT_TEMPLATE = DIR_CONFIG + 'defaults.ini'

GUI_REFRESH_INTERVAL = 16
AUTO_PLAY_ON_LOAD = True
AUTO_PAUSE_ON_LOAD = False

import sys
import os
import platform
import time
import logging

from lib.docopt import docopt

try:
    from lib.pyqtgraph import QtGui, QtCore  # ALL HAIL LUKE!
    import lib.pyqtgraph as pg
except ImportError:
    pg = None
    from PyQt4 import QtGui, QtCore

from lib.core import Spotter
from lib.ui.mainUi import Ui_MainWindow
from lib.ui import GLFrame, PGFrame
from lib.ui import SerialIndicator, StatusBar, SideBar, openDeviceDlg

if pg is not None:
    FRAME_BACKEND = PGFrame.PGFrame
else:
    FRAME_BACKEND = GLFrame


class Main(QtGui.QMainWindow):
    __spotter_ref = None

    def __init__(self, app, *args, **kwargs):  # , source, destination, fps, size, gui, serial
        self.log = logging.getLogger(__name__)
        QtGui.QMainWindow.__init__(self)
        self.app = app

        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        # Status Bar
        self.status_bar = StatusBar(self)
        self.statusBar().addWidget(self.status_bar)

        # Side bar
        self.side_bar = SideBar.SideBar(self)
        self.ui.frame_parameters.addWidget(self.side_bar)

        # Exit Signals
        self.ui.actionE_xit.setShortcut('Ctrl+Q')
        self.ui.actionE_xit.setStatusTip('Exit Spotter')
        self.connect(self.ui.actionE_xit, QtCore.SIGNAL('triggered()'), QtCore.SLOT('close()'))

        # About window
        self.connect(self.ui.actionAbout, QtCore.SIGNAL('triggered()'), self.about)

        # Persistent application settings
        # TODO: Needs command line option to reset everything
        self.settings = QtCore.QSettings()

        # Menu Bar items
        #   File Menu
        self.connect(self.ui.actionFile, QtCore.SIGNAL('triggered()'), self.file_open_video)
        self.connect(self.ui.actionCamera, QtCore.SIGNAL('triggered()'), self.file_open_device)
        self.recent_files = self.settings.value("RecentFiles").toStringList()
        self.connect(self.ui.actionClearRecentFiles, QtCore.SIGNAL('triggered()'), self.clear_recent_files)
        self.update_file_menu()

        #   Configuration/Template Menu
        self.connect(self.ui.actionLoadTemplate, QtCore.SIGNAL('triggered()'), self.load_template)
        self.connect(self.ui.actionSaveTemplate, QtCore.SIGNAL('triggered()'), self.save_template)
        self.connect(self.ui.actionRemoveTemplate, QtCore.SIGNAL('triggered()'),
                     self.side_bar.remove_all_tabs)
        self.connect(self.ui.actionClearRecentTemplates, QtCore.SIGNAL('triggered()'), self.clear_recent_templates)
        self.recent_templates = self.settings.value("RecentTemplates").toStringList()
        self.update_template_menu()

        # Toolbar items
        self.connect(self.ui.actionRecord, QtCore.SIGNAL('toggled(bool)'), self.toggle_record)
        self.ui.actionPlay.toggled.connect(self.toggle_play)
        self.ui.actionPause.toggled.connect(self.toggle_pause)
        self.ui.actionRepeat.toggled.connect(self.toggle_repeat)
        # self.ui.actionFastForward.triggered.connect(self.fast_forward)
        # self.ui.actionRewind.triggered.connect(self.rewind)
        self.ui.push_rewind.clicked.connect(self.rewind)
        self.ui.push_fast_forward.clicked.connect(self.fast_forward)
        #self.connect(self.ui.actionSourceProperties, QtCore.SIGNAL('triggered()'),
        #             self.spotter.grabber.get_capture_properties)

        # Serial/Arduino Connection status indicator
        self.arduino_indicator = SerialIndicator()
        self.ui.toolBar.addWidget(self.arduino_indicator)

        # OpenGL frame
        if pg is None:
            self.video_frame = FRAME_BACKEND(AA=True)
            self.ui.frame_video.addWidget(self.video_frame)
            self.video_frame.setSizePolicy(QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Expanding)
            # handling mouse events by the tabs for selection of regions etc.
            self.video_frame.sig_event.connect(self.mouse_event_to_tab)

        # PyQtGraph frame
        else:
            self.video_frame = FRAME_BACKEND()
            self.ui.gridLayout_2.addWidget(self.video_frame)

        # Video source timing scroll bar
        self.ui.scrollbar_pos.setVisible(False)
        self.ui.scrollbar_pos.actionTriggered.connect(self.video_pos_scrollbar_moved)

        # Main Window states
        self.resize(self.settings.value("MainWindow/Size", QtCore.QVariant(QtCore.QSize(600, 500))).toSize())
        self.move(self.settings.value("MainWindow/Position", QtCore.QVariant(QtCore.QPoint(0, 0))).toPoint())
        self.restoreState(self.settings.value("MainWindow/State").toByteArray())
        #self.center_window()
        on_top = True if self.settings.value("MainWindow/AlwaysOnTop").toInt()[0] else False
        self.ui.actionOnTop.setChecked(on_top)
        self.connect(self.ui.actionOnTop, QtCore.SIGNAL('toggled(bool)'), self.toggle_window_on_top)
        self.toggle_window_on_top(on_top)

        # starting values, likely overwritten during initialization
        self.playing = False
        self.paused = False
        self.repeat = False
        self.gui_fps = 30.0
        self.gui_fps_low = False
        self.gui_fps_low_now = False
        self.gui_refresh_offset = 0
        self.gui_refresh_interval = GUI_REFRESH_INTERVAL
        self.stopwatch = QtCore.QElapsedTimer()

        # fires when event loop starts
        QtCore.QTimer.singleShot(0, self.initialize)

    ###############################################################################
    ##                           SPOTTER CLASS INIT                               #
    ###############################################################################
    def initialize(self, *args, **kwargs):
        # Spotter main class, handles Grabber, Writer, Tracker, Chatter
        self.__spotter_ref = Spotter(*args, **kwargs)

        # populate side bar now that spotter is here...
        self.side_bar.initialize(self.spotter)
        self.arduino_indicator.initialize(self.spotter.chatter)

        self.stopwatch.start()
        self.new_source()
        self.refresh()

    @property
    def spotter(self):
        return self.__spotter_ref

    def new_source(self):
        """A new source has been opened, refresh UI elements."""
        # TODO: Force refresh with at least one new frame!
        self.log.debug('New source selected, updating UI elements.')

        if self.spotter.grabber.source:
            self.ui.actionPlay.setChecked(AUTO_PLAY_ON_LOAD)
            self.ui.actionPause.setChecked(AUTO_PAUSE_ON_LOAD)

            # Add file/source name to main window title and show status bar message
            title = ': '.join([self.spotter.grabber.source_type, str(self.spotter.grabber.source.source)])
            self.setWindowTitle('Spotter - %s' % title[0].upper()+title[1:])
            self.ui.statusbar.showMessage('Opened %s' % title[0].upper()+title[1:], 5000)

            # Play control UI elements (spin boxes, slider, frame num labels etc.)
            indexed = True if self.spotter.grabber.source_indexed else False
            self.ui.scrollbar_pos.setEnabled(indexed)
            num_frames = self.spotter.grabber.source_num_frames if indexed else 0
            self.ui.scrollbar_pos.setMaximum(num_frames)
            self.ui.spin_index.setMaximum(num_frames)
            self.ui.spin_index.setSuffix('/%d' % num_frames)
            self.ui.scrollbar_pos.setVisible(indexed)

    ###############################################################################
    ##                             FRAME REFRESH                                  #
    ###############################################################################
    def refresh(self):
        #self.log.debug('Refresh Main window')

        elapsed = self.stopwatch.restart()
        try:
            # Trigger grabbing and processing of new frame
            new_frame_available = self.spotter.update(self.playing)

            # Update the video frame display
            if all([self.playing, not self.paused, new_frame_available]):
                # Update Video Frame
                self.video_frame.update_world(self.spotter)

            # TODO: Show both video frame backends simultaneously for comparison
                # Update GL frame
                # if self.gl_frame is not None:
                #     if not (self.gl_frame.width and self.gl_frame.height):
                #         return
                #     self.gl_frame.update_world(self.spotter)
                # Update Video Frame
                # if self.pg_frame is not None:
                #     self.pg_frame.update_world(self.spotter)

            # Update the currently open tab
            #self.log.debug("Updating side bar")
            self.side_bar.update_current_page()

            # Check if the refresh rate needs adjustment
            #self.log.debug("Updating GUI refresh rate")
            self.adjust_refresh_rate()

        finally:
            self.update_ui_elements()
            # Based on stopwatch, show GUI refresh rate
            self.update_fps(elapsed)
            # start timer to next refresh
            QtCore.QTimer.singleShot(self.gui_refresh_interval, self.refresh)

    def update_ui_elements(self):
        """Awkward helper method to check on some notorious misfits..."""
        if self.spotter.grabber.source_indexed:
            index = self.spotter.grabber.source_index
            num_frames = self.spotter.grabber.source_num_frames
            if not self.ui.scrollbar_pos.value() == index:
                self.ui.scrollbar_pos.setValue(index)
            if not self.ui.spin_index.value() == self.ui.scrollbar_pos.value():
                #self.ui.scrollbar_pos.value()
                self.ui.spin_index.setValue(index)
        else:
            # Everything should have been disabled!
            pass

    def update_fps(self, elapsed):
        """Refresh the UI refresh rate indicator."""
        # TODO: This needs to be moved into its own widget or back into the status bar (StatusBar.py)
        if elapsed != 0:
            self.gui_fps = self.gui_fps*0.9 + 0.1*1000./elapsed
            if self.gui_fps > 100:
                self.ui.lbl_fps.setText('FPS: {:.0f}'.format(self.gui_fps))
            else:
                self.ui.lbl_fps.setText('FPS: {:.1f}'.format(self.gui_fps))

        self.gui_fps_low_now = self.gui_fps < 30

        if self.gui_fps_low_now != self.gui_fps_low:
            if self.gui_fps_low_now:
                self.gui_fps_low = True
                self.ui.lbl_fps.setStyleSheet(' QLabel {color: red}')
            else:
                self.gui_fps_low = False
                self.ui.lbl_fps.setStyleSheet(' QLabel {color: black}')

    def adjust_refresh_rate(self, forced=None):
        """Change GUI refresh rate according to frame rate of video source, or keep at
        1000/GUI_REFRESH_INTERVAL Hz for cameras to not miss too many frames
        """
        # TODO: Allow adjusting for the video, too.
        self.gui_refresh_offset = self.ui.spin_offset.value()

        # TODO: Adjust to 30 fps for now...
        try:
            frame_dur = int(1000.0 / (self.spotter.grabber.source_fps if self.spotter.grabber.source_fps else 30))
        except ValueError:
            frame_dur = int(1000.0 / 30.0)

        if forced is not None:
            self.gui_refresh_interval = forced
            return

        if self.spotter.grabber.source_type == 'file':
            if not self.ui.spin_offset.isEnabled():
                self.ui.spin_offset.setEnabled(True)
            try:
                interval = frame_dur + self.gui_refresh_offset
            except (ValueError, TypeError):
                interval = 0
            if interval < 0:
                interval = 0
                self.ui.spin_offset.setValue(interval - frame_dur)

            if frame_dur != 0 and self.gui_refresh_interval != interval:
                self.gui_refresh_interval = interval
                self.log.debug("Changed main loop update rate to match file. New: %d", self.gui_refresh_interval)
        else:
            if self.ui.spin_offset.isEnabled():
                self.ui.spin_offset.setEnabled(False)
            if self.gui_refresh_interval != GUI_REFRESH_INTERVAL:
                self.gui_refresh_interval = GUI_REFRESH_INTERVAL
                self.log.debug("Changed main loop update rate to be fast. New: %d", self.gui_refresh_interval)

    def toggle_play(self, state=None):
        """Start playback of video source sequence.
        """
        if self.spotter.grabber.source:
            self.playing = self.ui.actionPlay.isChecked()
            if not self.playing:
                self.ui.actionPause.setChecked(False)
                self.ui.actionPause.setEnabled(False)
            else:
                self.ui.actionPause.setEnabled(True)
        else:
            self.ui.actionPlay.setChecked(False)
            self.ui.actionPause.setChecked(False)

    def toggle_pause(self):
        """Pause playback _display_ at current frame.
        """
        self.paused = self.ui.actionPause.isChecked()

    def toggle_repeat(self):
        """Continuously loop over source sequence.
        """
        self.repeat = self.ui.actionRepeat.isChecked()
        if self.source is not None:
            self.source.repeat = self.repeat

    def toggle_record(self, state, filename=None):
        """Control recording of grabbed video."""
        # TODO: Pre-select output video file name to not slow down start too much by dialog
        # TODO: Records control side panel select range of filename choices, i.e.
        # Automatic choice of filename, filename selection dialog, custom string etc.
        self.log.debug("Toggling writer recording state")
        if state:
            if filename is None:
                filename = QtGui.QFileDialog.getSaveFileName(self, 'Open Video', './recordings/')
                if len(filename):
                    self.spotter.start_writer(str(filename) + '.avi')
        else:
            self.spotter.stop_writer()

    def video_pos_scrollbar_moved(self):
        """When the user moves the scrollbar or the spin box, update the index for the indexed
        video source.
        """
        if not self.spotter.grabber.source_indexed:
            return

        before = self.spotter.grabber.source_index
        # Move grabber index to new position if necessary
        #if not self.playing:
        if not self.spotter.grabber.source_index == self.ui.scrollbar_pos.value():
            #self.spotter.grabber.grab(self.ui.scrollbar_pos.value())
            self.spotter.grabber.source_index = self.ui.scrollbar_pos.value()
        print before, self.spotter.grabber.source_index, self.ui.scrollbar_pos.value()

    def rewind(self):
        self.spotter.grabber.rewind()

    def fast_forward(self):
        self.spotter.grabber.fast_forward()

    def mouse_event_to_tab(self, event_type, event):
        """Hand the mouse event to the active tab. Tabs may handle mouse events
        differently, and depending on internal states (e.g. selections)
        """
        current_tab = self.side_bar.get_child_page()
        if current_tab:
            try:
                if current_tab.accept_events:
                    current_tab.process_event(event_type, event)
            except AttributeError:
                pass

    def about(self):
        """About message box. Credits. Links. Jokes."""
        QtGui.QMessageBox.about(self, "About",
                                """<b>Spotter</b> v%s
                   <p>Copyright &#169; 2012-2014 <a href=mailto:ronny.eichler@gmail.com>Ronny Eichler</a>.
                   <p>This application is under heavy development. Use at your own risk.
                   <p>Python %s -  PyQt4 version %s - on %s""" % (__version__,
                                                                  platform.python_version(), QtCore.QT_VERSION_STR,
                                                                  platform.system()))

    def center_window(self):
        """Centers main window on screen. Doesn't quite work on multi-monitor setups,
        as the whole screen-area is taken. But as long as the window ends up in a
        predictable position...
        """
        screen = QtGui.QDesktopWidget().screenGeometry()
        window_size = self.geometry()
        self.move((screen.width() - window_size.width()) / 2, (screen.height() - window_size.height()) / 2)

    def toggle_window_on_top(self, state):
        """Have main window stay on top. According to the setWindowFlags
        documentation, the window will hide after changing flags, requiring
        either a .show() or a .raise(). These may have different behaviors on
        different platforms!"""
        # TODO: Test on OSX
        if state:
            self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
            self.show()
        else:
            self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowStaysOnTopHint)
            self.show()

    def file_open_video(self, filename=None, path=DIR_EXAMPLES):
        """Open a video file.

        Actions calling this function are not providing
        arguments, so self.sender() has to be checked for the calling action
        if no arguments were given.
        """
        path = QtCore.QString(path)

        # If no filename given, this is may be supposed to open a recent file
        if filename is None:
            action = self.sender()
            if isinstance(action, QtGui.QAction):
                filename = action.data().toString()

        # If filename is still None, this was called by the Open File action
        if not len(filename) or filename is None:
            filename = QtGui.QFileDialog.getOpenFileName(self, 'Open Video', path,
                                                         self.tr('Video: *.avi *.mpg *.mp4 ;; All Files: (*.*)'))

        # If the user chose a file, this is finally not None...
        if len(filename) and self.spotter.grabber.start(source=str(filename), source_type='file'):
            self.add_recent_file(filename)
            self.update_file_menu()
            self.new_source()
        else:
            self.ui.statusbar.showMessage('Failed to open %s' % filename, 5000)

    def file_open_device(self):
        """Open camera as frame source.
        """
        dialog = openDeviceDlg.OpenDeviceDlg()
        dialog.spin_width.setValue(640)
        dialog.spin_height.setValue(360)
        dialog.ledit_device.setText("0")
        if dialog.exec_() and self.spotter.grabber.start(source=dialog.ledit_device.text(),
                                                         source_type='camera',
                                                         size=(dialog.spin_width.value(), dialog.spin_height.value())):
            self.new_source()

    @staticmethod
    def add_actions(target, actions):
        for action in actions:
            if action is None:
                target.addSeparator()
            else:
                target.addAction(action)

    # RECENTLY OPENED FILES
    def update_file_menu(self):
        """Update list of recently opened files in the File->Open menu.
        """
        # throw everything out and start over...
        self.ui.menu_Open.clear()
        self.add_actions(self.ui.menu_Open, [self.ui.actionFile, self.ui.actionCamera, None])

        try:
            source_is_file = self.spotter is not None and self.spotter.grabber.source_type == 'file'
            if source_is_file:
                current_file = QtCore.QFileInfo(QtCore.QString(self.spotter.grabber.source.source)).fileName()
            else:
                current_file = None
        except TypeError:
            current_file = None

        # list of files to show in the menu, only append if file still exists!
        recent_files = []
        for filename in self.recent_files:
            if filename != current_file and QtCore.QFile.exists(filename):
                recent_files.append(filename)

        # Generate actions for each entry in the list and append to menu
        if recent_files:
            for i, filename in enumerate(recent_files):
                # TODO: Icons for the entries
                action = QtGui.QAction(QtGui.QIcon(":/icon.png"),
                                       "&%d %s" % (i + 1, QtCore.QFileInfo(filename).fileName()), self)
                action.setData(QtCore.QVariant(filename))
                self.connect(action, QtCore.SIGNAL("triggered()"), self.file_open_video)
                self.ui.menu_Open.addAction(action)
            # convenience action to remove all entries
            self.add_actions(self.ui.menu_Open, [None, self.ui.actionClearRecentFiles])

    def add_recent_file(self, filename):
        """Add file to the list of recently opened files.
         NB: self.recent_files is a QStringList, not a python list!
        """
        if filename is not None:
            if not self.recent_files.contains(filename):
                self.recent_files.prepend(QtCore.QString(filename))
                while self.recent_files.count() > 9:
                    self.recent_files.take_last()

    def clear_recent_files(self):
        """Remove all entries from the list of recently opened files.
        """
        self.recent_files.clear()
        self.update_file_menu()

    ###############################################################################
    ##                             TEMPLATE handling                              #
    ###############################################################################
    def load_template(self, filename=None, path=DIR_TEMPLATES):
        """Opens file dialog to choose template file and starts parsing it.
        """
        # TODO: Handle old relative coordinate style templates
        # Or simply disable relative templates?
        if self.spotter.grabber.source is None:
            self.ui.statusbar.showMessage("No video source! Can't load a template without in this version.", 5000)
            return

        # If no filename given, this is may be supposed to open a recent file
        if filename is None:
            action = self.sender()
            if isinstance(action, QtGui.QAction):
                filename = action.data().toString()

        if filename is None or not len(filename):
            path = QtCore.QString(path)
            filename = QtGui.QFileDialog.getOpenFileName(self, 'Open Template', path, self.tr('All Files: *.*'))
        if not len(filename):
            return
        else:
            filename = str(filename)

        template = self.spotter.load_template(filename)
        if template is not None:
            features, objects_, regions = self.spotter.apply_template(template)

            for f in features:
                self.side_bar.represent_feature(f, focus_new=False)

            for o in objects_:
                self.side_bar.represent_object(o, focus_new=False)

            for r in regions:
                self.side_bar.represent_region(r, focus_new=False)

            self.ui.statusbar.showMessage('Opened template %s' % filename, 5000)
            # Add opened file to list of recent templates
            self.add_recent_template(filename)
            self.update_template_menu()
        else:
            self.log.debug("Couldn't open template.")

    def save_template(self, filename=None, path=DIR_TEMPLATES):
        """Save current spotter state as template."""
        if filename is None:
            filename = str(QtGui.QFileDialog.getSaveFileName(self, 'Save Template', path))
        if not len(filename):
            return
        self.spotter.save_template(filename)

        # Add file to list of recent templates
        self.add_recent_template(filename)
        self.update_template_menu()

    def update_template_menu(self):
        """Update list of recently opened templates in the Template menu.
        """
        # throw everything out and start over...
        self.ui.menuTemplate.clear()
        self.add_actions(self.ui.menuTemplate, [self.ui.actionLoadTemplate,
                                                self.ui.actionSaveTemplate,
                                                self.ui.actionRemoveTemplate,
                                                None])

        # list of files to show in the menu, only append if file still exists!
        recent_templates = []
        for filename in self.recent_templates:
            if QtCore.QFile.exists(filename):
                recent_templates.append(filename)

        # Generate actions for each entry in the list and append to menu
        if recent_templates:
            for i, filename in enumerate(recent_templates):
                # TODO: Icons for the entries
                action = QtGui.QAction(QtGui.QIcon(":/icon.png"),
                                       "&%d %s" % (i + 1, QtCore.QFileInfo(filename).fileName()), self)
                action.setData(QtCore.QVariant(filename))
                self.connect(action, QtCore.SIGNAL("triggered()"), self.load_template)
                self.ui.menuTemplate.addAction(action)
            # convenience action to remove all entries
            self.add_actions(self.ui.menuTemplate, [None, self.ui.actionClearRecentTemplates])

    def add_recent_template(self, filename):
        """Add file to the list of recently opened files.
         NB: self.recent_files is a QStringList, not a python list!
        """
        if filename is not None:
            if not self.recent_templates.contains(filename):
                self.recent_templates.prepend(QtCore.QString(filename))
                while self.recent_templates.count() > 9:
                    self.recent_templates.take_last()

    def clear_recent_templates(self):
        """Remove all entries from the list of recently opened templates.
        """
        self.recent_templates.clear()
        self.update_template_menu()

    def store_settings(self):
        """Store window states and other settings.
        """
        settings = QtCore.QSettings()

        # Last opened file
        filename = QtCore.QVariant(QtCore.QString(self.spotter.grabber.source.source)) \
            if self.spotter.grabber.source_type == 'file' else QtCore.QVariant()
        settings.setValue("LastFile", filename)

        # Recently opened files
        recent_files = QtCore.QVariant(self.recent_files) if self.recent_files else QtCore.QVariant()
        settings.setValue("RecentFiles", recent_files)

        # Recently opened templates
        recent_templates = QtCore.QVariant(self.recent_templates) if self.recent_templates else QtCore.QVariant()
        settings.setValue("RecentTemplates", recent_templates)

        # Main Window states
        settings.setValue("MainWindow/Size", QtCore.QVariant(self.size()))
        settings.setValue("MainWindow/Position", QtCore.QVariant(self.pos()))
        settings.setValue("MainWindow/State", QtCore.QVariant(self.saveState()))
        on_top = int(self.windowFlags() & QtCore.Qt.WindowStaysOnTopHint)
        settings.setValue("MainWindow/AlwaysOnTop", QtCore.QVariant(on_top))

    def closeEvent(self, event):
        """Exiting the interface has to kill the spotter class and subclasses
        properly, especially the writer and serial handles, otherwise division
        by zero might be imminent.
        """
        if NO_EXIT_CONFIRMATION:
            reply = QtGui.QMessageBox.Yes
        else:
            reply = QtGui.QMessageBox.question(self, 'Exiting...', 'Are you sure?',
                                               QtGui.QMessageBox.Yes, QtGui.QMessageBox.No)
        if reply == QtGui.QMessageBox.Yes:
            self.store_settings()
            self.spotter.exit()
            event.accept()
        else:
            event.ignore()


#############################################################
def main(*args, **kwargs):
    app = QtGui.QApplication([])
    # identifiers for QSettings persistent application settings
    app.setOrganizationName('spotter_inc')
    app.setOrganizationDomain('spotter.sp')
    app.setApplicationName('Spotter')

    window = Main(app, *args, **kwargs)
    window.show()
    window.raise_()  # needed on OSX?

    sys.exit(app.exec_())


if __name__ == "__main__":  #
    #############################################################
    # TODO: Recover full command-line functionality
    # TODO: Add config file for general settings
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Command line parsing
    arg_dict = docopt.docopt(__doc__, version=None)
    DEBUG = arg_dict['--DEBUG']
    if DEBUG:
        print(arg_dict)

    # Frame size parameter string 'WIDTHxHEIGHT' to size tuple (WIDTH, HEIGHT)
    size = (640, 360) if not arg_dict['--dims'] else tuple(arg_dict['--dims'].split('x'))

    main(source=arg_dict['--source'], size=size)

    # Qt main window which instantiates spotter class with all parameters
    #main(source=arg_dict['--source'],
    #     destination=utils.dst_file_name(arg_dict['--outfile']),
    #     fps=arg_dict['--fps'],
    #     size=size,
    #     serial=arg_dict['--Serial'])
