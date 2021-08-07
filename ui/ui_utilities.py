"""
/***************************************************************************
 SwissGeoDownloader
                                 A QGIS plugin
 This plugin lets you comfortably download swiss geo data.
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
from datetime import datetime

from qgis.PyQt.QtCore import QCoreApplication

MESSAGE_CATEGORY = 'Swiss Geo Downloader'


def tr(message, **kwargs):
    """Get the translation for a string using Qt translation API.
    We implement this ourselves since we do not inherit QObject.
    """
    return QCoreApplication.translate('@default', message)


def formatCoordinate(number):
    """Format big numbers with thousand separator, swiss-style"""
    if number is None:
        return ''
    # Format big numbers with thousand separator
    elif number >= 1000:
        return f"{number:,.0f}".replace(',', "'")
    else:
        return f"{number:,.6f}"
    

def castToNum(formattedNum):
    """Casts formatted numbers back to floats"""
    if type(formattedNum) in [int, float]:
        return formattedNum
    try:
        num = float(formattedNum.replace("'", ''))
    except (ValueError, AttributeError):
        num = None
    return num


def filesizeFormatter(num, suffix='B'):
    """Formats data sizes to human readable units"""
    for unit in ['','K','M','G','T','P','E','Z']:
        if abs(num) < 1024.0:
            return "%3.1f %s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f %s%s" % (num, 'Yi', suffix)


def getDateFromIsoString(isoString, formatted=True):
    """Translate ISO date string to date or swiss date format"""
    if type(isoString) != str or not isoString:
        return ''
    if isoString[-1] == 'Z':
        isoString = isoString[:-1]
    try:
        dt = datetime.fromisoformat(isoString)
    except ValueError as e:
        return None
    if formatted:
        return dt.strftime('%d.%m.%Y')
    else:
        return dt

