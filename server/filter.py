# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: t -*-
# vi: set ft=python sts=4 ts=4 sw=4 noet :

# This file is part of Fail2Ban.
#
# Fail2Ban is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Fail2Ban is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Fail2Ban; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

# Author: Cyril Jaquier
#
# $Revision$

__author__ = "Cyril Jaquier"
__version__ = "$Revision$"
__date__ = "$Date$"
__copyright__ = "Copyright (c) 2004 Cyril Jaquier"
__license__ = "GPL"

from failmanager import FailManagerEmpty
from failmanager import FailManager
from ticket import FailTicket
from jailthread import JailThread
from datedetector import DateDetector
from mytime import MyTime
from failregex import FailRegex, Regex, RegexException
from dnsutils import DNSUtils

import logging, re, os, fcntl, time, socket

# Gets the instance of the logger.
logSys = logging.getLogger("fail2ban.filter")

##
# Log reader class.
#
# This class reads a log file and detects login failures or anything else
# that matches a given regular expression. This class is instantiated by
# a Jail object.

class Filter(JailThread):

	##
	# Constructor.
	#
	# Initialize the filter object with default values.
	# @param jail the jail object

	def __init__(self, jail, useDns='warn', ipv6banprefix=64):
		JailThread.__init__(self)
		## The jail which contains this filter.
		self.jail = jail
		## The failures manager.
		self.failManager = FailManager()
		## The regular expression list matching the failures.
		self.__failRegex = list()
		## The regular expression list with expressions to ignore.
		self.__ignoreRegex = list()
		## Use DNS setting
		self.setUseDns(useDns)
		## The amount of time to look back.
		self.__findTime = 6000
		## The ignore IP list.
		self.__ignoreIpList = []
		## The IPv6 ban prefix
		self._ipv6banprefix = ipv6banprefix

		self.dateDetector = DateDetector()
		self.dateDetector.addDefaultTemplate()
		logSys.debug("Created %s" % self)


	def __repr__(self):
		return "%s(%r)" % (self.__class__.__name__, self.jail)

	##
	# Add a regular expression which matches the failure.
	#
	# The regular expression can also match any other pattern than failures
	# and thus can be used for many purporse.
	# @param value the regular expression

	def addFailRegex(self, value):
		try:
			regex = FailRegex(value)
			self.__failRegex.append(regex)
		except RegexException, e:
			logSys.error(e)
			raise e


	def delFailRegex(self, index):
		try:
			del self.__failRegex[index]
		except IndexError:
			logSys.error("Cannot remove regular expression. Index %d is not "
						 "valid" % index)

	##
	# Get the regular expression which matches the failure.
	#
	# @return the regular expression

	def getFailRegex(self):
		failRegex = list()
		for regex in self.__failRegex:
			failRegex.append(regex.getRegex())
		return failRegex

	##
	# Add the regular expression which matches the failure.
	#
	# The regular expression can also match any other pattern than failures
	# and thus can be used for many purpose.
	# @param value the regular expression

	def addIgnoreRegex(self, value):
		try:
			regex = Regex(value)
			self.__ignoreRegex.append(regex)
		except RegexException, e:
			logSys.error(e)
			raise e 

	def delIgnoreRegex(self, index):
		try:
			del self.__ignoreRegex[index]
		except IndexError:
			logSys.error("Cannot remove regular expression. Index %d is not "
						 "valid" % index)

	##
	# Get the regular expression which matches the failure.
	#
	# @return the regular expression

	def getIgnoreRegex(self):
		ignoreRegex = list()
		for regex in self.__ignoreRegex:
			ignoreRegex.append(regex.getRegex())
		return ignoreRegex

	##
	# Set the Use DNS mode
	# @param value the usedns mode

	def setUseDns(self, value):
		if isinstance(value, bool):
			value = {True: 'yes', False: 'no'}[value]
		value = value.lower()			  # must be a string by now
		if not (value in ('yes', 'no', 'warn')):
			logSys.error("Incorrect value %r specified for usedns. "
						 "Using safe 'no'" % (value,))
			value = 'no'
		logSys.debug("Setting usedns = %s for %s" % (value, self))
		self.__useDns = value

	##
	# Get the usedns mode
	# @return the usedns mode

	def getUseDns(self):
		return self.__useDns

	##
	# Set the time needed to find a failure.
	#
	# This value tells the filter how long it has to take failures into
	# account.
	# @param value the time

	def setFindTime(self, value):
		self.__findTime = value
		self.failManager.setMaxTime(value)
		logSys.info("Set findtime = %s" % value)

	##
	# Get the time needed to find a failure.
	#
	# @return the time

	def getFindTime(self):
		return self.__findTime

	##
	# Set the maximum retry value.
	#
	# @param value the retry value

	def setMaxRetry(self, value):
		self.failManager.setMaxRetry(value)
		logSys.info("Set maxRetry = %s" % value)

	##
	# Get the maximum retry value.
	#
	# @return the retry value

	def getMaxRetry(self):
		return self.failManager.getMaxRetry()

	##
	# Set the IPv6 ban Prefix
	#
	# @param value the retry value

	def setIPv6BanPrefix(self, value):
		self._ipv6banprefix = value
		# logging done in Jail class

	##
	# Get the IPv6 ban Prefix
	#
	# @return the retry value

	def getIPv6BanPrefix(self):
		return self._ipv6banprefix

	##
	# Main loop.
	#
	# This function is the main loop of the thread. It checks if the
	# file has been modified and looks for failures.
	# @return True when the thread exits nicely

	def run(self): # pragma: no cover
		raise Exception("run() is abstract")

	##
	# Ban an IP - http://blogs.buanzo.com.ar/2009/04/fail2ban-patch-ban-ip-address-manually.html
	# Arturo 'Buanzo' Busleiman <buanzo@buanzo.com.ar>
	#
	# to enable banip fail2ban-client BAN command

	def addBannedIP(self, ip):
		unixTime = MyTime.time()
		s = ip.split('/', 1)
		family = DNSUtils.ipFamily(s[0])
		# IP address without CIDR mask
		if len(s) == 1:
			if family == socket.AF_INET6:
				s.insert(1, 128)
			else:
				s.insert(1, 32)
		prefix = s[1]

		for i in xrange(self.failManager.getMaxRetry()):
			self.failManager.addFailure(FailTicket(s[0], family , unixTime))

		# Perform the banning of the IP now.
		try: # pragma: no branch - exception is the only way out
			while True:
				ticket = self.failManager.toBan(prefix)
				self.jail.putFailTicket(ticket)
		except FailManagerEmpty:
			self.failManager.cleanup(MyTime.time())

		return ip

	##
	# Add an IP/DNS to the ignore list.
	#
	# IP addresses in the ignore list are not taken into account
	# when finding failures. CIDR mask and DNS are also accepted.
	# @param ip IP address to ignore

	def addIgnoreIP(self, ip):
		family = DNSUtils.ipFamily(ip)
		if not family:
			ips = DNSUtils.dnsToIp(ip)
			if ips:
				logSys.info(ip + " not recognised as IP address. Assuming to be a Domain Name")
			else:
				logSys.error(ip + " not recognised as IP address and domain resolution doesn't return anything. Ignoring")
				return	
		logSys.debug("Add " + ip + " to ignore list")
		self.__ignoreIpList.append( (family,ip))

	def delIgnoreIP(self, ip):
		family = DNSUtils.ipFamily(ip)
		logSys.debug("Remove " + ip + " from ignore list")
		self.__ignoreIpList.remove( (family,ip) )

	def getIgnoreIP(self):
		return [item[1] for item in self.__ignoreIpList]

	def getIgnoreFamilyIPList(self):
		return self.__ignoreIpList

	##
	# Check if IP address/DNS is in the ignore list.
	#
	# Check if the given IP address matches an IP address/DNS or a CIDR
	# mask in the ignore list.
	# @param ip IP address
	# @return True if IP address is in ignore list

	def inIgnoreIPList(self, ip, family=False):
		if not family:
			family = DNSUtils.ipFamily(ip)
		for ifamily,i in self.__ignoreIpList:
			if ifamily:
				if family != ifamily:
					continue
				s = i.split('/', 1)
				# IP address without CIDR mask
				if len(s) == 1:
					if family == socket.AF_INET6:
						s.insert(1, 128)
					else:
						s.insert(1, 32)
				else:
					s[1] = int(s[1])
				a = DNSUtils.cidr(s[0], s[1], ifamily)
				b = DNSUtils.cidr(ip, s[1], family)
				if a == b:
					logSys.debug("IP %s family %d found for ignore list" % (ip, family))
					return True
				continue # pragma: no cover - error in coverage tool https://bitbucket.org/ned/coveragepy/issue/198
			# Check if IP in DNS
			ips = DNSUtils.dnsToIp(i)
			for lfam,ipaddr in ips:
				if family == lfam and ip == ipaddr:
					logSys.debug("IP %s family %d found for ignore list after DNS lookup match -> %s" % (ip, family, i))
					return True

		logSys.debug("IP %s family %d not in ignore list" % (ip, family))
		return False


	def processLine(self, line):
		"""Split the time portion from log msg and return findFailures on them
		"""
		try:
			# Decode line to UTF-8
			l = line.decode('utf-8')
		except UnicodeDecodeError:
			l = line
		timeMatch = self.dateDetector.matchTime(l)
		if timeMatch:
			# Lets split into time part and log part of the line
			timeLine = timeMatch.group()
			# Lets leave the beginning in as well, so if there is no
			# anchore at the beginning of the time regexp, we don't
			# at least allow injection. Should be harmless otherwise
			logLine  = l[:timeMatch.start()] + l[timeMatch.end():]
		else:
			timeLine = l
			logLine = l
		return self.findFailure(timeLine, logLine)

	def processLineAndAdd(self, line):
		"""Processes the line for failures and populates failManager
		"""
		for element in self.processLine(line):
			ip = element[0]
			family = element[1]
			unixTime = element[2]
			logSys.debug("Processing line with time:%s and ip:%s"
						 % (unixTime, ip))
			if unixTime < MyTime.time() - self.getFindTime():
				logSys.debug("Ignore line since time %s < %s - %s"
							 % (unixTime, MyTime.time(), self.getFindTime()))
				break
			if self.inIgnoreIPList(ip, family):
				logSys.debug("Ignore %s" % ip)
				continue
			logSys.debug("Found %s" % ip)
			if family == socket.AF_INET6:
				self.failManager.addFailure(
					FailTicket(DNSUtils.truncatetoprefix(ip, self._ipv6banprefix, family),
								 family, unixTime, matches=[line],
								 prefix=self._ipv6banprefix)
				)
			else:
				self.failManager.addFailure(FailTicket(ip, family, unixTime,  matches=[line]))

	##
	# Returns true if the line should be ignored.
	#
	# Uses ignoreregex.
	# @param line: the line
	# @return: a boolean

	def ignoreLine(self, line):
		for ignoreRegex in self.__ignoreRegex:
			ignoreRegex.search(line)
			if ignoreRegex.hasMatched():
				return True
		return False

	##
	# Finds the failure in a line given split into time and log parts.
	#
	# Uses the failregex pattern to find it and timeregex in order
	# to find the logging time.
	# @return a dict with IP and timestamp.

	def findFailure(self, timeLine, logLine):
		failList = list()
		# Checks if we must ignore this line.
		if self.ignoreLine(logLine):
			# The ignoreregex matched. Return.
			return failList
		# Iterates over all the regular expressions.
		for failRegex in self.__failRegex:
			failRegex.search(logLine)
			if failRegex.hasMatched():
				# The failregex matched.
				date = self.dateDetector.getUnixTime(timeLine)
				if date == None:
					logSys.debug("Found a match for %r but no valid date/time "
								 "found for %r. Please file a detailed issue on"
								 " https://github.com/fail2ban/fail2ban/issues "
								 "in order to get support for this format."
								 % (logLine, timeLine))
				else:
					try:
						host = failRegex.getHost()
						ipMatch = DNSUtils.textToIp(host, self.__useDns)
						if ipMatch:
							for family,ip in ipMatch:
								failList.append([ip, family, date])
							# We matched a regex, it is enough to stop.
							break
					except RegexException, e: # pragma: no cover - unsure if reachable
						logSys.error(e)
		return failList


	##
	# Get the status of the filter.
	#
	# Get some informations about the filter state such as the total
	# number of failures.
	# @return a list with tuple

	def status(self):
		ret = [("Currently failed", self.failManager.size()),
		       ("Total failed", self.failManager.getFailTotal())]
		return ret


class FileFilter(Filter):

	def __init__(self, jail, **kwargs):
		Filter.__init__(self, jail, **kwargs)
		## The log file path.
		self.__logPath = []

	##
	# Add a log file path
	#
	# @param path log file path

	def addLogPath(self, path, tail = False):
		if self.containsLogPath(path):
			logSys.error(path + " already exists")
		else:
			container = FileContainer(path, tail)
			self.__logPath.append(container)
			logSys.info("Added logfile = %s" % path)
			self._addLogPath(path)			# backend specific

	def _addLogPath(self, path):
		# nothing to do by default
		# to be overridden by backends
		pass


	##
	# Delete a log path
	#
	# @param path the log file to delete

	def delLogPath(self, path):
		for log in self.__logPath:
			if log.getFileName() == path:
				self.__logPath.remove(log)
				logSys.info("Removed logfile = %s" % path)
				self._delLogPath(path)
				return
		logSys.error(path + " not in filter")

	def _delLogPath(self, path): # pragma: no cover - seems to be optimised away from coverage
		# nothing to do by default
		# to be overridden by backends
		pass

	##
	# Get the log file path
	#
	# @return log file path

	def getLogPath(self):
		return self.__logPath

	##
	# Check whether path is already monitored.
	#
	# @param path The path
	# @return True if the path is already monitored else False

	def containsLogPath(self, path):
		for log in self.__logPath:
			if log.getFileName() == path:
				return True
		return False

	def getFileContainer(self, path):
		for log in self.__logPath:
			if log.getFileName() == path:
				return log
		return None

	##
	# Gets all the failure in the log file.
	#
	# Gets all the failure in the log file which are newer than
	# MyTime.time()-self.findTime. When a failure is detected, a FailTicket
	# is created and is added to the FailManager.

	def getFailures(self, filename):
		container = self.getFileContainer(filename)
		if container == None:
			logSys.error("Unable to get failures in " + filename)
			return False
		# Try to open log file.
		try:
			container.open()
		# see http://python.org/dev/peps/pep-3151/
		except IOError, e:
			logSys.error("Unable to open %s" % filename)
			logSys.exception(e)
			return False
		except OSError, e: # pragma: no cover - requires race condition to tigger this
			logSys.error("Error opening %s" % filename)
			logSys.exception(e)
			return False
		except OSError, e: # pragma: no cover - Requires implemention error in FileContainer to generate
			logSys.error("Internal errror in FileContainer open method - please report as a bug to https://github.com/fail2ban/fail2ban/issues")
			logSys.exception(e)
			return False

		while True:
			line = container.readline()
			if (line == "") or not self._isActive():
				# The jail reached the bottom or has been stopped
				break
			self.processLineAndAdd(line)
		container.close()
		return True

	def status(self):
		ret = Filter.status(self)
		path = [m.getFileName() for m in self.getLogPath()]
		ret.append(("File list", path))
		return ret

##
# FileContainer class.
#
# This class manages a file handler and takes care of log rotation detection.
# In order to detect log rotation, the hash (MD5) of the first line of the file
# is computed and compared to the previous hash of this line.

try:
	import hashlib
	md5sum = hashlib.md5
except ImportError: # pragma: no cover
	# hashlib was introduced in Python 2.5.  For compatibility with those
	# elderly Pythons, import from md5
	import md5
	md5sum = md5.new

class FileContainer:

	def __init__(self, filename, tail = False):
		self.__filename = filename
		self.__tail = tail
		self.__handler = None
		# Try to open the file. Raises an exception if an error occured.
		handler = open(filename)
		stats = os.fstat(handler.fileno())
		self.__ino = stats.st_ino
		try:
			firstLine = handler.readline()
			# Computes the MD5 of the first line.
			self.__hash = md5sum(firstLine).digest()
			# Start at the beginning of file if tail mode is off.
			if tail:
				handler.seek(0, 2)
				self.__pos = handler.tell()
			else:
				self.__pos = 0
		finally:
			handler.close()

	def getFileName(self):
		return self.__filename

	def getPos(self):
		return self.__pos

	def open(self):
		self.__handler = open(self.__filename)
		# Set the file descriptor to be FD_CLOEXEC
		fd = self.__handler.fileno()
		fcntl.fcntl(fd, fcntl.F_SETFD, fd | fcntl.FD_CLOEXEC)
		firstLine = self.__handler.readline()
		# Computes the MD5 of the first line.
		myHash = md5sum(firstLine).digest()
		stats = os.fstat(self.__handler.fileno())
		# Compare hash and inode
		if self.__hash != myHash or self.__ino != stats.st_ino:
			logSys.debug("Log rotation detected for %s" % self.__filename)
			self.__hash = myHash
			self.__ino = stats.st_ino
			self.__pos = 0
		# Sets the file pointer to the last position.
		self.__handler.seek(self.__pos)

	def readline(self):
		if self.__handler == None:
			return ""
		return self.__handler.readline()

	def close(self):
		if not self.__handler == None:
			# Saves the last position.
			self.__pos = self.__handler.tell()
			# Closes the file.
			self.__handler.close()
			self.__handler = None


