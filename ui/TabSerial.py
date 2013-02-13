# -*- coding: utf-8 -*-
"""
Created on Sun Jan 18 21:13:54 2013
@author: <Ronny Eichler> ronny.eichler@gmail.com


"""

import sys
from time import sleep
from PyQt4 import QtGui, QtCore

sys.path.append('./lib')
import utilities as utils

sys.path.append('./ui')
from tab_serialUi import Ui_tab_serial

tab_type = "region"

class Tab(QtGui.QWidget, Ui_tab_serial):

    label = None
    serial = None
    accept_events = False
    tab_type = "serial"

    def __init__(self, parent, serial_handle, label = None):
        self.serial = serial_handle
        if label == None:
            self.label = self.serial.label
        else:
            self.label = label
            self.serial.label = label

        super(QtGui.QWidget, self).__init__(parent)
        self.parent = parent
        self.setupUi(self)

        self.connect(self.btn_serial_refresh, QtCore.SIGNAL('clicked()'), self.refresh_port_list)
        self.connect(self.btn_serial_connect, QtCore.SIGNAL('clicked()'), self.toggle_connection)
        self.btn_serial_connect.setCheckable(True)

        self.refresh_port_list()
        self.update()


    def update(self):
        if self.serial.is_connected():
            if not self.btn_serial_connect.isChecked():
                self.btn_serial_connect.setText('Disconnect')
                self.btn_serial_connect.setChecked(True)
            # Human readable values of bytes sent/received
            tx = utils.binary_prefix(self.serial.bytes_tx())
            rx = utils.binary_prefix(self.serial.bytes_rx())
            self.lbl_bytes_sent.setText(tx)
            self.lbl_bytes_received.setText(rx)
        else:
            self.btn_serial_connect.setText('Connect')
            self.btn_serial_connect.setChecked(False)

    def refresh_port_list(self):
        """ Populates the list of available serial ports in the machine.
        May not work under windows at all. Would then require the user to
        provide the proper port. Either via command line or typing it into the
        combobox.
        """
        candidate = None
        for i in range(self.combo_serialports.count()):
            self.combo_serialports.removeItem(i)
        for p in self.serial.list_ports():
            if len(p) > 2 and "USB" in p[2]:
                candidate = p
            self.combo_serialports.addItem(p[0])
        if candidate:
            self.combo_serialports.setCurrentIndex(self.combo_serialports.findText(candidate[0]))


    def toggle_connection(self):
        """
        Toggle button to either connect or disconnect serial connection.
        """
        # This test is inversed. When the function is called the button is
        # already pressed, i.e. checked -> representing future state, not past
        if not self.btn_serial_connect.isChecked():
            self.btn_serial_connect.setText('Connect')
            self.btn_serial_connect.setChecked(False)
            self.serial.close()
            self.parent.update_all_tabs()
        else:
            self.serial.serial_port = str(self.combo_serialports.currentText())
            try:
#                sc = self.serial.open_serial(self.serial.serial_port)
                sc = self.serial.auto_connect(self.serial.serial_port)
            except:
                print "Connection failed! But I won't tell you why..."
#                self.btn_serial_connect.setText('Connect')
                self.btn_serial_connect.setChecked(False)
                return
            if sc:
                self.btn_serial_connect.setText('Disconnect')
                self.btn_serial_connect.setChecked(True)
                self.parent.update_all_tabs()