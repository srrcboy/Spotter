"""
Created on Sun Jan 13 14:19:24 2013
@author: <Ronny Eichler> ronny.eichler@gmail.com

Status Bar widget holding fps counter, frame buffer indicator, etc.
"""

import sys
from PyQt4 import QtGui, QtCore

sys.path.append('./ui')
from statusBarUi import Ui_statusBar


class StatusBarWidget(QtGui.QWidget, Ui_statusBar):

    def __init__(self, parent):
        super(QtGui.QWidget, self).__init__(parent)
        self.setupUi(self)