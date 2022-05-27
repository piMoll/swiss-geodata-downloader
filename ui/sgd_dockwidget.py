"""
/***************************************************************************
 SwissGeoDownloaderDockWidget
                                 A QGIS plugin
 This plugin lets you comfortably download swiss geo data.
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                             -------------------
        begin                : 2021-03-14
        copyright            : (C) 2022 by Patricia Moll
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
from qgis.PyQt.QtWidgets import (QDockWidget, QFileDialog, QMessageBox)
from qgis.gui import QgsExtentGroupBox, QgisInterface
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsProject, QgsRectangle, QgsApplication,
                       QgsMessageLog, Qgis)
from .sgd_dockwidget_base import Ui_sgdDockWidgetBase
from .waitingSpinnerWidget import QtWaitingSpinner
from .ui_utilities import filesizeFormatter, MESSAGE_CATEGORY
from .qgis_utilities import (addToQgis, addOverviewMap, transformBbox,
                             switchToCrs, RECOMMENDED_CRS)
from .datsetListTable import DatasetListTable
from .fileListTable import FileListTable
from .bboxDrawer import BboxPainter
from ..api.responseObjects import Dataset, ALL_VALUE, CURRENT_VALUE
from ..api.datageoadmin import ApiDataGeoAdmin, API_EPSG
from ..api.apiCallerTask import ApiCallerTask

VERSION = Qgis.QGIS_VERSION_INT

class SwissGeoDownloaderDockWidget(QDockWidget, Ui_sgdDockWidgetBase):

    closingPlugin = pyqtSignal()

    LABEL_DEFAULT_STYLE = 'QLabel { color : black; font-weight: normal;}'
    LABEL_SUCCESS_STYLE = 'QLabel { color : green; font-weight: bold;}'
    

    def __init__(self, interface: QgisInterface, locale, parent=None):
        """Constructor."""
        super(SwissGeoDownloaderDockWidget, self).__init__(parent)
        self.setupUi(self)
        self.iface = interface
        self.locale = locale
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
        self.currentFilters = {
            'filetype': None,
            'format': None,
            'resolution': None,
            'timestamp': None,
            'coordsys': None,
        }
        
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
        # Set current (=map view) extent
        self.guiExtentWidget.setCurrentExtent(self.canvas.extent(),
                                        self.mapRefSys)
        self.guiExtentWidget.setOutputExtentFromCurrent()
        
        # Initialize class to draw bbox of files in map
        self.bboxPainter = BboxPainter(self.canvas,
                                       self.transformApi2Proj, self.annManager)

        # Dataset and file list table
        self.datasetListTbl = DatasetListTable(self, self.guiDatasets)
        self.datasetListTbl.sig_selectionChanged.connect(self.onDatasetSelectionChange)
        
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
        
        self.filterFields = {
            'filetype': self.guiFileType,
            'format': self.guiFormat,
            'resolution': self.guiResolution,
            'timestamp': self.guiTimestamp,
            'coordsys': self.guiCoordsys,
        }
        
        self.filterFieldLabels = {
            'filetype': self.guiFileTypeL,
            'format': self.guiFormatL,
            'resolution': self.guiResolutionL,
            'timestamp': self.guiTimestampL,
            'coordsys': self.guiCoordsysL,
        }
        
        # API caller task
        self.fileListRequest = None
        self.guiRequestCancelBtn.setHidden(True)

        # Deactivate unused ui-elements
        self.guiGroupExtent.setDisabled(True)
        self.guiExtentWidget.setCollapsed(True)
        self.guiGroupFiles.setDisabled(True)
        self.guiDownloadBtn.setDisabled(True)
        
        self.guiFileType.currentIndexChanged.connect(self.onFilterChanged)
        self.guiFormat.currentTextChanged.connect(self.onFilterChanged)
        self.guiResolution.currentIndexChanged.connect(self.onFilterChanged)
        self.guiTimestamp.currentIndexChanged.connect(self.onFilterChanged)
        self.guiCoordsys.currentIndexChanged.connect(self.onFilterChanged)
        
        self.guiExtentWidget.extentChanged.connect(self.onExtentChanged)
        self.guiFullExtentChbox.clicked.connect(self.onUseFullExtentClicked)
        
        self.guiRequestListBtn.clicked.connect(self.onLoadFileListClicked)
        self.guiDownloadBtn.clicked.connect(self.onDownloadFilesClicked)
        self.guiQuestionBtn.clicked.connect(self.onQuestionClicked)
        self.guiRequestCancelBtn.clicked.connect(self.onCancelRequestClicked)
        
        self.qgsProject.crsChanged.connect(self.onMapRefSysChanged)
        self.canvas.extentsChanged.connect(self.onMapExtentChanged)
        self.iface.newProjectCreated.connect(self.resetFileList)
        self.canvas.scaleChanged.connect(self.setBboxVisibility)
        
        # Check current project crs and ask user to change it
        self.checkSupportedCrs()
        
        # Finally, initialize apis and request available datasets
        self.apiDGA = ApiDataGeoAdmin(self, self.locale)
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
        """ Update output extent when the following cases occur:
        2 - User changes coordinates in extent fields
        3 - User selects a layer from option 'calculate from layer'
        """
        if self.guiExtentWidget.extentState() in [2, 3]:
            newExtent = self.guiExtentWidget.outputExtent()
            extentCrs = self.guiExtentWidget.outputCrs()
            
            # If extent originates from a layer and layer extent does not match
            #  map coordinate system, transform the extent
            if self.guiExtentWidget.extentState() == 3 \
                    and extentCrs != self.mapRefSys and extentCrs.isValid():
                transformer = QgsCoordinateTransform(extentCrs,
                                self.mapRefSys, self.qgsProject)
                trafoRectangle = transformBbox(newExtent, transformer)
                newExtent = QgsRectangle(*tuple(trafoRectangle))
            
            self.guiExtentWidget.setCurrentExtent(newExtent, self.mapRefSys)
    
    def onMapExtentChanged(self):
        """Show extent of current map view in extent widget."""
        if self.guiExtentWidget.extentState() == 1:
            # Only update widget if its current state is to display the map
            #  view extent
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

    def setBboxVisibility(self):
        if not self.bboxPainter:
            return
        self.bboxPainter.switchNumberVisibility()
    
    def onReceiveDatasets(self, datasetList):
        """Recieve list of available datasets"""
        self.datasetList = datasetList
        self.datasetListTbl.fill(self.datasetList.values())
        self.spinnerDs.stop()
    
    def onDatasetSelectionChange(self, datasetId):
        """Set dataset and load details on first selection"""
        # Ignore double clicks or very fast clicks
        if self.currentDataset and datasetId == self.currentDataset.id:
            return
        if not datasetId:
            self.onUnselectDataset()
            return
        
        self.currentDataset = self.datasetList[datasetId]
        
        if not self.currentDataset.analysed:
            caller = ApiCallerTask(self.apiDGA, self.msgBar, 'getDatasetDetails',
                                   {'dataset': self.currentDataset})
            # Listen for finished api call
            caller.taskCompleted.connect(
                lambda: self.onLoadDatasetDetails(caller.output))
            caller.taskTerminated.connect(
                lambda: self.onLoadDatasetDetails())
            self.taskManager.addTask(caller)
        else:
            self.onLoadDatasetDetails()
    
    def onLoadDatasetDetails(self, dataset=None):
        if dataset:
            self.datasetList[dataset.id] = dataset
            self.currentDataset = dataset
        self.applyDatasetState()
        
        # If dataset has only a single file to download, get it right away
        if self.currentDataset.isSingleFile:
            self.onLoadFileListClicked()
    
    def onQuestionClicked(self):
        title = self.tr('Why are there no files?')
        msg = self.tr("Not all datasets cover the whole area of Switzerland."
                     " Try changing options or select 'Full dataset extent'"
                     " to get a list of all available datasets.")
        self.showDialog(title, msg, 'Ok')
    
    def applyDatasetState(self):
        """Set up ui according to the options of the selected dataset"""
        # Show dataset status if no files are available
        if not self.currentDataset or self.currentDataset.isEmpty:
            self.guiGroupExtent.setDisabled(True)
            self.guiExtentWidget.setCollapsed(True)
            self.guiGroupFiles.setDisabled(True)
            self.resetFileList()
            self.fileListTbl.onEmptyList(self.tr('No files available in this dataset'))
            return
        
        self.deactivateFilterElem()

        # Activate / deactivate 2. Extent
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
    
    def blockFilterSignals(self):
        for uiElem in self.filterFields.values():
            uiElem.blockSignals(True)
    
    def unblockFilterSignals(self):
        for uiElem in self.filterFields.values():
            uiElem.blockSignals(False)
      
    def emptyFileFilters(self):
        self.blockFilterSignals()
        for uiElem in self.filterFields.values():
            uiElem.clear()
        self.unblockFilterSignals()
    
    def resetCurrentlySelectedFilters(self):
        for key in self.currentFilters.keys():
            self.currentFilters[key] = None
    
    def deactivateFilterElem(self, filterItem=''):
        if filterItem:
            self.filterFields[filterItem].setDisabled(True)
            self.filterFields[filterItem].setHidden(True)
            self.filterFieldLabels[filterItem].setDisabled(True)
            self.filterFieldLabels[filterItem].setHidden(True)
            return
        
        for uiElem in self.filterFields.values():
            uiElem.setEnabled(False)
            uiElem.setHidden(True)
        for labelElem in self.filterFieldLabels.values():
            labelElem.setEnabled(False)
            labelElem.setHidden(True)

    def activateFilterElem(self, filterItem=''):
        if filterItem:
            self.filterFields[filterItem].setEnabled(True)
            self.filterFields[filterItem].setHidden(False)
            self.filterFieldLabels[filterItem].setEnabled(True)
            self.filterFieldLabels[filterItem].setHidden(False)
            return
        
        for uiElem in self.filterFields.values():
            uiElem.setEnabled(True)
            uiElem.setHidden(False)
        for labelElem in self.filterFieldLabels.values():
            labelElem.setEnabled(True)
            labelElem.setHidden(False)
        
    def onUnselectDataset(self):
        self.currentDataset = {}
        
        self.onReceiveFileList([])
        self.guiGroupExtent.setDisabled(True)
        self.guiExtentWidget.setCollapsed(True)
        self.guiGroupFiles.setDisabled(True)
        self.guiDownloadBtn.setDisabled(True)
    
    def resetFileList(self):
        self.fileList = []
        self.fileListFiltered = {}
        self.fileListTbl.clear()
        self.guiDownloadBtn.setDisabled(True)
        self.guiFileListStatus.setText('')
        self.guiFileListStatus.setStyleSheet(self.LABEL_DEFAULT_STYLE)
        self.bboxPainter.removeAll()
    
    def onOptionChanged(self, newVal):
        self.resetFileList()
    
    def onFilterChanged(self, newVal):
        for fileName, uiElem in self.filterFields.items():
            filterVal = uiElem.currentData()
            if filterVal:
                self.currentFilters[fileName] = filterVal
        
        self.applyFilters()
    
    def updateSelectMode(self):
        if self.guiFullExtentChbox.isChecked():
            bbox = QgsRectangle(*tuple(self.currentDataset.bbox))
            self.updateExtentValues(bbox, self.apiRefSys)
    
    def getBbox(self) -> list:
        """Read out coordinates of bounding box, transform coordinates if
        necessary"""
        if self.guiFullExtentChbox.isChecked() or \
                not self.guiExtentWidget.isEnabled():
            return []
        
        rectangle = self.guiExtentWidget.currentExtent()
        return transformBbox(rectangle, self.transformProj2Api)

    def onLoadFileListClicked(self):
        """Collect options and call api to retrieve list of items"""
        # Remove current file list
        self.resetFileList()
        
        # Read out extent
        bbox = self.getBbox()
        if float('inf') in bbox:
            bbox = []
        
        # Call api
        # Create a separate task for request to not block ui
        self.fileListRequest = ApiCallerTask(self.apiDGA, self.msgBar,
            'getFileList', {'url': self.currentDataset.filesLink, 'bbox': bbox})
        # Listen for finished api call
        self.fileListRequest.taskCompleted.connect(
            lambda: self.onReceiveFileList(self.fileListRequest.output))
        self.fileListRequest.taskTerminated.connect(
            lambda: self.onReceiveFileList({}))
        # Start spinner to indicate data loading
        self.spinnerFl.start()
        self.guiRequestCancelBtn.setHidden(False)
        # Add task to task manager
        self.taskManager.addTask(self.fileListRequest)

    def onCancelRequestClicked(self):
        if self.fileListRequest:
            self.fileListRequest.cancel()
            self.guiRequestCancelBtn.setHidden(True)

    def onReceiveFileList(self, fileList):
        self.guiRequestCancelBtn.setHidden(True)
        if not fileList:
            fileList = {'files': [], 'filters': None}
        if not fileList['files']:
            fileList['files'] = []
        self.fileList = fileList['files']
        # Update file type filter and file list
        self.updateFilterFields(fileList['filters'])
        self.applyFilters()

        # Enable download button
        if self.fileList:
            self.guiDownloadBtn.setDisabled(False)

        self.spinnerFl.stop()
    
    def updateFilterFields(self, filters):
        self.emptyFileFilters()

        if not filters:
            self.resetCurrentlySelectedFilters()
            self.deactivateFilterElem()
            return
        
        self.blockFilterSignals()
        
        for filterName, uiElem in self.filterFields.items():
            filterVals = filters[filterName]
            for filterVal in filterVals:
                uiElem.addItem(self.formatFilterVal(filterVal, filterName), filterVal)
            
            if len(filterVals) > 1:
                # Show filter and set current filter value
                self.activateFilterElem(filterName)
                
                if self.currentFilters[filterName] in filterVals:
                    idx = uiElem.findData(self.currentFilters[filterName])
                    uiElem.setCurrentIndex(idx)
                else:
                    self.currentFilters[filterName] = filterVals[0]
                    
            else:
                # Hide filter and unset current filter value
                self.deactivateFilterElem(filterName)
                self.currentFilters[filterName] = None

        self.unblockFilterSignals()
    
    def formatFilterVal(self, val, filterName):
        if val == ALL_VALUE:
            return self.tr('all')
        elif val == CURRENT_VALUE:
            return self.tr('current')
            
        elif filterName == 'coordsys':
            # Create a coordinate system object and get its friendly identifier
            cs = QgsCoordinateReferenceSystem(f'EPSG:{val}')
            if VERSION < 31003:
                return cs.description()
            else:
                return cs.userFriendlyIdentifier()
        else:
            return val
    
    def populateFileList(self, fileList):
        # There are files but all of them are currently filtered out
        if (self.fileList and not fileList):
            self.fileListTbl.onEmptyList(self.tr('Currently selected filters do not match any files'))
        else:
            self.fileListTbl.fill(fileList)
        self.updateSummary()
    
    def applyFilters(self):
        self.fileListFiltered = {}
        orderedFilesForTbl = []
        for file in self.fileList:
            
            if (file.filetypeFitsFilter(self.currentFilters['filetype'])
                and file.formatFitsFilter(self.currentFilters['format'])
                and file.resolutionFitsFilter(self.currentFilters['resolution'])
                and file.timestampFitsFilter(self.currentFilters['timestamp'])
                and file.coordsysFitsFilter(self.currentFilters['coordsys'])
            ):
                file.selected = True
                self.fileListFiltered[file.id] = file
                # This list is necessary because dictionaries do not have a
                #  stable order, but we want the original order from the
                #  API response in the table
                orderedFilesForTbl.append(file)
            else:
                file.selected = False

        self.populateFileList(orderedFilesForTbl)
        self.bboxPainter.paintBoxes(self.fileListFiltered)

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
    
    def cleanCanvas(self):
        if self.bboxPainter:
            self.bboxPainter.removeAll()
    
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
