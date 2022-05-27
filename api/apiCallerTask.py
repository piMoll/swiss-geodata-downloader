"""
/***************************************************************************
 SwissGeoDownloader
                                 A QGIS plugin
 This plugin lets you comfortably download swiss geo data.
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
from qgis.core import QgsTask, QgsMessageLog, Qgis
from ..ui.ui_utilities import MESSAGE_CATEGORY


class ApiCallerTask(QgsTask):
    def __init__(self, apiRef, msgBar, func, callParams):
        description = func
        super().__init__(description, QgsTask.CanCancel)
        self.apiRef = apiRef
        self.msgBar = msgBar
        self.func = func
        self.callParams = callParams
        self.output = None
        self.exception = None
    
    def run(self):
        """Here the time-consuming requests are started. This method MUST
         return True or False. Raising exceptions will crash QGIS, so we
         handle them internally and raise them in self.finished()"""
        
        if self.func == 'getDatasetList':
            self.output = self.apiRef.getDatasetList(self)
        
        elif self.func == 'getDatasetDetails':
            self.output = self.apiRef.getDatasetDetails(self,
                                        self.callParams['dataset'])
        
        elif self.func == 'getFileList':
            self.output = self.apiRef.getFileList(self,
                                        self.callParams['url'],
                                        self.callParams['bbox'])
        
        elif self.func == 'downloadFiles':
            self.output = self.apiRef.downloadFiles(self,
                                        self.callParams['fileList'],
                                        self.callParams['folder'])
        return True
    
    def finished(self, result):
        """This function is automatically called when the task has
        completed (successfully or not)"""
        if result and self.output is not False:
            msg = self.tr('request completed')
            if self.func == 'getDatasetList':
                msg = self.tr('available datasets received')
            elif self.func == 'getFileList':
                msg = self.tr('file list received')
            elif self.func == 'downloadFiles':
                msg = self.tr('files downloaded')
            self.log(msg, Qgis.Success)
        else:
            if self.isCanceled():
                self.log(self.tr('Aborted by user'), Qgis.Info)
            elif self.exception is None:
                self.exception = self.tr('An unknown error occurred')
                self.log(self.exception, Qgis.Critical)
                self.message(self.exception, Qgis.Warning)
            else:
                self.log(self.exception, Qgis.Critical)
                self.message(self.exception, Qgis.Warning)

    def log(self, msg, level=Qgis.Info):
        QgsMessageLog.logMessage(str(msg), MESSAGE_CATEGORY, level)
    
    def message(self, msg, level=Qgis.Info):
        self.msgBar.pushMessage(f"{MESSAGE_CATEGORY}: {msg}", level)

    def cancel(self):
        super().cancel()
