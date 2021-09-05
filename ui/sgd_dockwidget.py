"""
/***************************************************************************
 SwissGeoDownloaderDockWidget
                                 A QGIS plugin
 This plugin lets you comfortably download swiss geo data.
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                             -------------------
        begin                : 2021-03-14
        copyright            : (C) 2021 by Patricia Moll
        email                : pimoll.dev@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (QDockWidget, QListWidget, QFileDialog,
                                 QMessageBox)
from qgis.gui import QgsExtentGroupBox, QgisInterface
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsProject, QgsRectangle, QgsApplication,
                       QgsMessageLog, Qgis)
from .sgd_dockwidget_base import Ui_sgdDockWidgetBase
from .waitingSpinnerWidget import QtWaitingSpinner
from .ui_utilities import (filesizeFormatter, getDateFromIsoString,
                           MESSAGE_CATEGORY)
from .qgis_utilities import (addToQgis, addOverviewMap, transformBbox,
                             switchToCrs, RECOMMENDED_CRS)
from .fileListTable import FileListTable
from .bboxDrawer import BboxPainter
from ..api.responseObjects import Dataset
from ..api.datageoadmin import ApiDataGeoAdmin, API_EPSG
from ..api.apiCallerTask import ApiCallerTask

VERSION = Qgis.QGIS_VERSION_INT

class SwissGeoDownloaderDockWidget(QDockWidget, Ui_sgdDockWidgetBase):

    closingPlugin = pyqtSignal()

    LABEL_DEFAULT_STYLE = 'QLabel { color : black; font-weight: normal;}'
    LABEL_SUCCESS_STYLE = 'QLabel { color : green; font-weight: bold;}'
    

    def __init__(self, interface: QgisInterface, parent=None):
        """Constructor."""
        super(SwissGeoDownloaderDockWidget, self).__init__(parent)
        self.setupUi(self)
        self.iface = interface
        self.canvas = self.iface.mapCanvas()
        self.qgsProject = QgsProject.instance()
        self.taskManager = QgsApplication.taskManager()
        self.annManager = self.qgsProject.annotationManager()

        # Initialize variables
        self.datasetList = {}
        self.currentDataset: Dataset = Dataset()
        self.selectMode = None
        self.fileList = []
        self.fileListFiltered = {}
        self.filesListDownload = []
        self.currentFilter = None
        self.outputPath = None
        self.msgBar = self.iface.messageBar()
        self.msgLog = QgsMessageLog()
        
        # Coordinate system
        self.mapRefSys = self.canvas.mapSettings().destinationCrs()
        self.apiRefSys = QgsCoordinateReferenceSystem(API_EPSG)
        self.transformProj2Api = QgsCoordinateTransform(
            self.mapRefSys, self.apiRefSys, self.qgsProject)
        self.transformApi2Proj = QgsCoordinateTransform(
            self.apiRefSys, self.mapRefSys, self.qgsProject)
        
        # Init QgsExtentBoxGroup Widget
        self.guiExtentWidget: QgsExtentGroupBox
        self.guiExtentWidget.setOriginalExtent(self.canvas.extent(),
                                         self.mapRefSys)
        # Set current (=map view) extent
        self.guiExtentWidget.setCurrentExtent(self.canvas.extent(),
                                        self.mapRefSys)
        self.guiExtentWidget.setOutputExtentFromCurrent()
        
        # Initialize class to draw bbox of files in map
        self.bboxPainter = BboxPainter(self.canvas,
                                       self.transformApi2Proj, self.annManager)

        # Deactivate unused ui-elements
        self.onUnselectDataset()
        self.guiDatasetStatus.hide()
        self.guiQuestionBtn.hide()
        self.questionTxt = []

        # File list table
        self.fileListTbl = FileListTable(self, self.guiFileListLayout)
        self.fileListTbl.sig_selectionChanged.connect(self.onFileSelectionChange)
        
        # Create spinners to indicate data loading
        # Spinner for dataset request
        self.spinnerDs = QtWaitingSpinner(self)
        self.spinnerDs.setRoundness(70.0)
        self.spinnerDs.setMinimumTrailOpacity(15.0)
        self.spinnerDs.setTrailFadePercentage(70.0)
        self.spinnerDs.setNumberOfLines(16)
        self.spinnerDs.setLineLength(16)
        self.spinnerDs.setLineWidth(5)
        self.spinnerDs.setInnerRadius(12)
        self.spinnerDs.setRevolutionsPerSecond(1)
        self.spinnerDs.setColor(QColor(100, 100, 100))
        self.verticalLayout.addWidget(self.spinnerDs)
        self.spinnerDs.start()
        
        # Spinner for file list request
        self.spinnerFl = QtWaitingSpinner(self)
        self.spinnerFl.setRoundness(70.0)
        self.spinnerFl.setMinimumTrailOpacity(15.0)
        self.spinnerFl.setTrailFadePercentage(70.0)
        self.spinnerFl.setNumberOfLines(16)
        self.spinnerFl.setLineLength(16)
        self.spinnerFl.setLineWidth(5)
        self.spinnerFl.setInnerRadius(12)
        self.spinnerFl.setRevolutionsPerSecond(1)
        self.spinnerFl.setColor(QColor(100, 100, 100))
        self.guiFileListLayout.addWidget(self.spinnerFl)
        
        # Connect signals
        self.guiShowMapBtn.clicked.connect(self.onShowMapClicked)
        self.guiRefreshDatasetsBtn.clicked.connect(self.onRefreshDatasetsClicked)
        self.guiInfoBtn.clicked.connect(self.onInfoClicked)
        
        self.guiDatasetList.currentItemChanged.connect(self.onDatasetSelected)
        self.guiFormat.currentTextChanged.connect(self.onOptionChanged)
        self.guiResolution.currentIndexChanged.connect(self.onOptionChanged)
        self.guiCoordsys.currentIndexChanged.connect(self.onOptionChanged)
        self.guiTimestamp.currentIndexChanged.connect(self.onOptionChanged)
        
        self.guiExtentWidget.extentChanged.connect(self.onExtentChanged)
        self.guiFullExtentChbox.clicked.connect(self.onUseFullExtentClicked)
        
        self.guiRequestListBtn.clicked.connect(self.onLoadFileListClicked)
        self.guiDownloadBtn.clicked.connect(self.onDownloadFilesClicked)
        self.guiFileType.currentIndexChanged.connect(self.onFilterOptionChanged)
        self.guiQuestionBtn.clicked.connect(self.onQuestionClicked)
        
        self.qgsProject.crsChanged.connect(self.onMapRefSysChanged)
        self.canvas.extentsChanged.connect(self.onMapExtentChanged)
        
        # Check current project crs and ask user to change it
        self.checkSupportedCrs()
        
        # Finally, initialize apis and request available datasets
        self.apiDGA = ApiDataGeoAdmin(self)
        self.loadDatasetList()

    def closeEvent(self, event):
        self.bboxPainter.removeAll()
        self.closingPlugin.emit()
        event.accept()
    
    def loadDatasetList(self):
        # Create separate task for request to not block ui
        caller = ApiCallerTask(self.apiDGA, self.msgBar, 'getDatasetList', {})
        # Listen for finished api call
        caller.taskCompleted.connect(
            lambda: self.onReceiveDatasets(caller.output))
        caller.taskTerminated.connect(
            lambda: self.onReceiveDatasets([]))
        self.taskManager.addTask(caller)
    
    def onMapRefSysChanged(self):
        """Listen for map canvas reference system changes and apply the new
        crs to extent widget."""
        self.mapRefSys = self.canvas.mapSettings().destinationCrs()
        # Update transformations
        self.transformProj2Api = QgsCoordinateTransform(
            self.mapRefSys, self.apiRefSys, self.qgsProject)
        self.transformApi2Proj = QgsCoordinateTransform(
            self.apiRefSys, self.mapRefSys, self.qgsProject)
        # Update displayed extent
        mapExtent: QgsRectangle = self.canvas.extent()
        self.updateExtentValues(mapExtent, self.mapRefSys)
        # Redraw bbox in map
        self.bboxPainter.transformer = self.transformApi2Proj
        self.bboxPainter.paintBoxes(self.fileListFiltered)
    
    def checkSupportedCrs(self):
        if self.mapRefSys.authid() not in RECOMMENDED_CRS:
            # If project is empty, we set the project crs automatically to LV95
            if len(self.qgsProject.mapLayers()) == 0:
                switchToCrs(self.qgsProject, self.canvas)
                return True
    
            confirmed = self.showDialog('Swiss Geo Downloader',
                self.tr('To download Swiss geo data it is recommended to use '
                        'the Swiss coordinate reference system.\n\nSwitch map '
                        'to Swiss LV95?'), 'YesNo')
            if confirmed:
                switchToCrs(self.qgsProject, self.canvas)
            else:
                return
        return True
    
    def onExtentChanged(self):
        pass
    
    def onMapExtentChanged(self):
        """Show extent of current map view in extent widget."""
        if self.guiExtentWidget.extentState() == 1:
            # Only update widget if its current state is to display the map
            #  view extent
            if self.guiGroupExtent.isEnabled() and self.guiExtentWidget.isEnabled():
                # Check if extent widget is currently active
                mapExtent: QgsRectangle = self.canvas.extent()
                self.updateExtentValues(mapExtent, self.mapRefSys)
    
    def onUseFullExtentClicked(self):
        if self.guiFullExtentChbox.isChecked():
            self.updateSelectMode()
            self.guiExtentWidget.setDisabled(True)
        else:
            self.guiExtentWidget.setDisabled(False)
            self.resetFileList()
            self.onMapExtentChanged()
    
    def onFilterOptionChanged(self, idx):
        if idx != -1:
            selectedFileType = self.guiFileType.itemText(idx)
            self.filterFileList(selectedFileType)
    
    def onShowMapClicked(self):
        self.checkSupportedCrs()
        message, level = addOverviewMap(self.qgsProject, self.canvas,
                                        self.mapRefSys.authid())
        self.msgBar.pushMessage(f"{MESSAGE_CATEGORY}: {message}", level)
    
    def onRefreshDatasetsClicked(self):
        self.resetFileList()
        self.onUnselectDataset()
        self.loadDatasetList()
    
    def onInfoClicked(self):
        self.showDialog(self.tr('Swiss Geo Downloader - Info'),
            self.tr('PLUGIN_INFO').format('https://pimoll.github.io/swissgeodownloader/'), 'Ok')
    
    def updateExtentValues(self, extent, refSys):
        self.guiExtentWidget.setCurrentExtent(extent, refSys)
        self.guiExtentWidget.setOutputExtentFromCurrent()
    
    def onReceiveDatasets(self, datasetList):
        """Recieve list of available datasets"""
        self.datasetList = datasetList
        self.guiDatasetList.blockSignals(True)
        self.guiDatasetList.clearSelection()
        self.guiDatasetList.clear()
        if self.datasetList:
            for dsId in self.datasetList.keys():
                self.guiDatasetList.addItem(dsId)
        self.guiDatasetList.blockSignals(False)
        self.spinnerDs.stop()
    
    def onDatasetSelected(self, item: QListWidget):
        """Set dataset and load details on first selection"""
        self.currentDataset = self.datasetList[item.text()]
        
        if not self.currentDataset.analysed:
            caller = ApiCallerTask(self.apiDGA, self.msgBar, 'getDatasetDetails',
                                   {'dataset': self.currentDataset})
            # Listen for finished api call
            caller.taskCompleted.connect(
                lambda: self.onLoadDatasetDetails(caller.output))
            caller.taskTerminated.connect(
                lambda: self.onLoadDatasetDetails(None))
            self.taskManager.addTask(caller)
        else:
            self.applyDatasetState()
    
    def onLoadDatasetDetails(self, dataset):
        if dataset:
            self.datasetList[dataset.id] = dataset
            self.currentDataset = dataset
        self.applyDatasetState()
    
    def onQuestionClicked(self):
        self.showDialog(self.questionTxt[0], self.questionTxt[1], 'Ok')
    
    def applyDatasetState(self):
        """Set up ui according to the options of the selected dataset"""
        # Show dataset in search field
        # self.guiSearchField.setText(self.currentDataset['id'])
        
        # Activate options and extent groups
        self.clearOptions()
        self.blockUiSignals()
        
        # Show dataset status if no files are available
        if self.currentDataset.isEmpty:
            self.guiGroupOptions.setDisabled(True)
            self.guiGroupExtent.setDisabled(True)
            self.guiExtentWidget.setCollapsed(True)
            self.guiGroupFiles.setDisabled(True)
            self.resetFileList()
            self.guiDatasetStatus.show()
            self.guiDatasetStatus.setStyleSheet('QLabel { color : red; }')
            self.guiDatasetStatus.setText(self.tr('No files available in this dataset'))
            return
        else:
            self.guiDatasetStatus.setText('')
            self.guiDatasetStatus.hide()
        
        # Setup 2. Options
        self.guiGroupOptions.setDisabled(False)
        dsOptions = self.currentDataset.options
        if dsOptions.format:
            self.guiFormat.addItems(dsOptions.format)
            # Only enable option if there is more than one choice
            if len(dsOptions.format) > 1:
                self.guiFormatL.setDisabled(False)
                self.guiFormat.setDisabled(False)
        if dsOptions.resolution:
            # Stringify resolution numbers
            optionStr = [str(r) for r in dsOptions.resolution]
            self.guiResolution.addItems(optionStr)
            if len(dsOptions.resolution) > 1:
                self.guiResolutionL.setDisabled(False)
                self.guiResolution.setDisabled(False)
        if dsOptions.coordsys:
            # Create a coordinate system object and get its friendly identifier
            coordSysList = [QgsCoordinateReferenceSystem(f'EPSG:{epsg}') for epsg in dsOptions.coordsys]
            if VERSION < 31003:
                coordSysNames = [cs.description() for cs in coordSysList]
            else:
                coordSysNames = [cs.userFriendlyIdentifier() for cs in coordSysList]
            self.guiCoordsys.addItems(coordSysNames)
            if len(dsOptions.coordsys) > 1:
                self.guiCoordsysL.setDisabled(False)
                self.guiCoordsys.setDisabled(False)
        if dsOptions.timestamp:
            # Format ISO time string into nice dates
            optionStr = [getDateFromIsoString(ts) for ts in dsOptions.timestamp]
            self.guiTimestamp.addItems(optionStr)
            if len(dsOptions.timestamp) > 1:
                self.guiTimestampL.setDisabled(False)
                self.guiTimestamp.setDisabled(False)

        # Activate / deactivate 3. Extent
        if not self.currentDataset.selectByBBox:
            self.guiExtentWidget.setCollapsed(True)
            self.updateSelectMode()
            self.guiGroupExtent.setDisabled(True)
        else:
            self.updateSelectMode()
            self.guiExtentWidget.setCollapsed(False)
            self.guiGroupExtent.setDisabled(False)
        
        # Activate 4. Files
        self.guiGroupFiles.setDisabled(False)
        self.resetFileList()
        
        self.unblockUiSignals()
        
    def clearOptions(self):
        """Deactivate and disable option drop down menus"""
        self.blockUiSignals()
        self.guiFormat.clear()
        self.guiFormat.setDisabled(True)
        self.guiFormatL.setDisabled(True)
        self.guiResolution.clear()
        self.guiResolution.setDisabled(True)
        self.guiResolutionL.setDisabled(True)
        self.guiCoordsys.clear()
        self.guiCoordsys.setDisabled(True)
        self.guiCoordsysL.setDisabled(True)
        self.guiTimestamp.clear()
        self.guiTimestamp.setDisabled(True)
        self.guiTimestampL.setDisabled(True)
        self.unblockUiSignals()
    
    def blockUiSignals(self):
        self.guiFormat.blockSignals(True)
        self.guiResolution.blockSignals(True)
        self.guiCoordsys.blockSignals(True)
        self.guiTimestamp.blockSignals(True)
        self.guiFullExtentChbox.blockSignals(True)
    
    def unblockUiSignals(self):
        self.guiFormat.blockSignals(False)
        self.guiResolution.blockSignals(False)
        self.guiCoordsys.blockSignals(False)
        self.guiTimestamp.blockSignals(False)
        self.guiFullExtentChbox.blockSignals(False)
        
    def onUnselectDataset(self):
        self.currentDataset = {}
        self.clearOptions()

        self.guiGroupOptions.setDisabled(True)
        self.guiGroupExtent.setDisabled(True)
        self.guiExtentWidget.setCollapsed(True)
        self.guiGroupFiles.setDisabled(True)
        self.guiDownloadBtn.setDisabled(True)
    
    def resetFileList(self):
        self.fileListTbl.clear()
        self.guiDownloadBtn.setDisabled(True)
        self.guiFileListStatus.setText('')
        self.guiFileListStatus.setStyleSheet(self.LABEL_DEFAULT_STYLE)
        self.guiQuestionBtn.hide()
        self.bboxPainter.removeAll()
    
    def onOptionChanged(self, newVal):
        self.resetFileList()
    
    def updateSelectMode(self):
        if self.guiFullExtentChbox.isChecked():
            bbox = QgsRectangle(*tuple(self.currentDataset.bbox))
            self.updateExtentValues(bbox, self.apiRefSys)
    
    def getBbox(self) -> list:
        """Read out coordinates of bounding box, transform coordinates if
        necessary"""
        if self.guiFullExtentChbox.isChecked():
            return []
        
        rectangle = self.guiExtentWidget.currentExtent()
        return transformBbox(rectangle, self.transformProj2Api)

    def onLoadFileListClicked(self):
        """Collect options and call api to retrieve list of items"""
        # Remove current file list
        self.fileListTbl.clear()
        
        # Read out extent
        bbox = self.getBbox()
        if float('inf') in bbox:
            bbox = []
            
        # Read out options
        reqOptions = {}
        timestamp = ''
        dsOptions = self.currentDataset.options
        # Only add to query parameters if there is more than one choice
        if len(dsOptions.format) > 1:
            reqOptions['format'] = dsOptions.format[self.guiFormat.currentIndex()]
        if len(dsOptions.resolution) > 1:
            reqOptions['resolution'] = dsOptions.resolution[self.guiResolution.currentIndex()]
        if len(dsOptions.coordsys) > 1:
            reqOptions['coordsys'] = dsOptions.coordsys[self.guiCoordsys.currentIndex()]
        if len(dsOptions.timestamp) > 1:
            timestamp = dsOptions.timestamp[self.guiTimestamp.currentIndex()]
        
        # Call api
        # Create a separate task for request to not block ui
        caller = ApiCallerTask(self.apiDGA, self.msgBar, 'getFileList', {
            'url': self.currentDataset.filesLink,
            'bbox': bbox,
            'timestamp': timestamp,
            'options': reqOptions
        })
        # Listen for finished api call
        caller.taskCompleted.connect(
            lambda: self.onReceiveFileList(caller.output))
        caller.taskTerminated.connect(
            lambda: self.onReceiveFileList(None))
        # Start spinner to indicate data loading
        self.spinnerFl.start()
        # Add task to task manager
        self.taskManager.addTask(caller)
    
    def onReceiveFileList(self, fileList):
        if not fileList:
            fileList = []
        self.fileList = fileList
        # Update file type filter and file list
        self.updateFilterList()
        self.filterFileList(self.currentFilter)

        # Enable download button
        if self.fileList:
            self.guiDownloadBtn.setDisabled(False)

        self.spinnerFl.stop()
    
    def updateFilterList(self):
        self.guiFileType.blockSignals(True)
        self.guiFileType.clear()
        # Get unique values from extension list by transforming list to a set
        fileTypeList = list(set([file.ext for file in self.fileList]))

        if fileTypeList:
            self.guiFileType.addItems(fileTypeList)
            # If previously selected file type is not in list anymore, select
            #  the first item in the list
            if self.currentFilter not in fileTypeList:
                self.currentFilter = fileTypeList[0]
            
            self.guiFileType.setCurrentIndex(fileTypeList.index(self.currentFilter))
        else:
            self.currentFilter = None
        self.guiFileType.blockSignals(False)
    
    def populateFileList(self, fileList):
        self.fileListTbl.fill(fileList)
        self.updateSummary()

    def filterFileList(self, filetype):
        self.fileListFiltered = {}
        orderedFilesForTbl = []
        for file in self.fileList:
            if not filetype or (filetype and file.ext == filetype):
                file.selected = True
                self.fileListFiltered[file.id] = file
                # This list is necessary because dictionaries do not have a
                #  stable order, but we want the original order from the
                #  API response in the table
                orderedFilesForTbl.append(file)
            else:
                file.selected = False
                
        self.currentFilter = filetype
        self.populateFileList(orderedFilesForTbl)
        self.bboxPainter.paintBoxes(self.fileListFiltered)
    
    def onFileSelectionChange(self, fileId, isChecked):
        self.fileListFiltered[fileId].selected = isChecked
        self.bboxPainter.switchSelectState(fileId)
        self.updateSummary()
    
    def updateSummary(self):
        self.guiQuestionBtn.hide()

        if self.fileListFiltered:
            fileSize = 0
            count = 0
            for file in self.fileListFiltered.values():
                if file.selected:
                    count += 1
                    if file.type in self.currentDataset.avgSize.keys():
                        fileSize += self.currentDataset.avgSize[file.type]
    
                # fileSize = sum([file.avgSize for file in self.fileListFiltered])
                
            if fileSize > 0:
                status = self.tr("{} file(s), approximately {}")\
                    .format(count, filesizeFormatter(fileSize))
            else:
                status = self.tr("{} file(s)").format(count)
        else:
            status = self.tr('No files found.')
            self.guiQuestionBtn.show()
            self.questionTxt = \
                [self.tr('Why are there no files?'),
                 self.tr("Not all datasets cover the whole area of Switzerland."
                         " Try changing options or select 'Full dataset extent'"
                         " to get a list of all available datasets.")]

        self.guiFileListStatus.setText(status)
        self.guiFileListStatus.setStyleSheet(self.LABEL_DEFAULT_STYLE)
    
    def onDownloadFilesClicked(self):
        # Let user choose output directory
        if self.outputPath:
            openDir = self.outputPath
        else:
            openDir = os.path.expanduser('~')
        folder = QFileDialog.getExistingDirectory(self,
                    self.tr('Choose output folder'), openDir, QFileDialog.ShowDirsOnly)
        if not folder:
            return
            
        # Save path for later
        self.outputPath = folder
        # Check if there are files that are going to be overwritten
        waitForConfirm = False
        # Sort out all selected files from list
        self.filesListDownload = []
        for file in self.fileListFiltered.values():
            if file.selected:
                file.path = os.path.join(folder, file.id)
                self.filesListDownload.append(file)
                if os.path.exists(file.path):
                    waitForConfirm = True
        
        if waitForConfirm:
            confirmed = self.showDialog(self.tr('Overwrite files?'),
                self.tr('At least one file will be overwritten. Continue?'))
            if not confirmed:
                self.filesListDownload = []
                return

        # Call api
        # Create separate task for request to not block ui
        caller = ApiCallerTask(self.apiDGA, self.msgBar, 'downloadFiles', {
            'fileList': self.filesListDownload,
            'folder': folder,
        })
        # Listen for finished api call
        caller.taskCompleted.connect(
            lambda: self.onFinishDownload(caller.output))
        caller.taskTerminated.connect(
            lambda: self.onFinishDownload(False))
        # Start spinner to indicate data loading
        self.spinnerFl.start()
        # Add task to task manager
        self.taskManager.addTask(caller)
    
    def onFinishDownload(self, success):
        if success:
            # Confirm successful download
            self.guiFileListStatus.setText(self.tr('Files successfully downloaded!'))
            self.guiFileListStatus.setStyleSheet(self.LABEL_SUCCESS_STYLE)
            self.fileListTbl.clear()
            self.bboxPainter.removeAll()
            self.msgBar.pushMessage(f"{MESSAGE_CATEGORY}: "
                + self.tr('{} file(s) successfully downloaded').format(
                            len(self.filesListDownload)), Qgis.Success)

        self.spinnerFl.stop()
        
        # Add file as layers to qgis
        addToQgis(self.qgsProject, self.filesListDownload)
    
    @staticmethod
    def showDialog(title, msg, mode='OkCancel'):
        msgBox = QMessageBox()
        msgBox.setIcon(QMessageBox.Question)
        msgBox.setWindowTitle(title)
        msgBox.setText(msg)
        if mode == 'OkCancel':
            msgBox.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        elif mode == 'YesNo':
            msgBox.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        elif mode == 'error':
            msgBox.setIcon(QMessageBox.Critical)
            msgBox.setStandardButtons(QMessageBox.Ok)
        elif mode == 'Ok':
            msgBox.setStandardButtons(QMessageBox.Ok)
        else:
            msgBox.setStandardButtons(QMessageBox.Ok)
            
        returnValue = msgBox.exec()
        return returnValue == QMessageBox.Ok or returnValue == QMessageBox.Yes
