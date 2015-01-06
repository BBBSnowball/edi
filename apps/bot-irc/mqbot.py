#!/usr/bin/env python
# -*- coding: utf-8 -*-
# ✓

"""
EDI IRC bot
"""

# Encoding Note: Expects IO to be in utf-8. Will break otherwise.

import time
import json
import logging

from threading import Thread

from twisted.words.protocols import irc
from twisted.internet import reactor, protocol, ssl, defer

from amqplib import client_0_8 as amqp

from config import AMQP_SERVER, config


__author__  = "Marcel Lauhoff, Patrick Meyer"
__email__   = "edi@irq0.org"
__license__ = "GPL"


logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger("irc-bot")

class MQ(Thread):
    def __init__(self, bot):
        Thread.__init__(self)
        self.daemon = True
        self.bot = bot
        self.init_connection()

    def init_connection(self):
        self.conn = amqp.Connection(host=AMQP_SERVER)
        self.chan = self.conn.channel()
        self.exchange = "msg"

        self.consumer_tags = []

        self.chan.exchange_declare(exchange=self.exchange,
                                   durable=True,
                                   auto_delete=False,
                                   type="topic")

        result = self.chan.queue_declare(exclusive=True)
        self.send_queue_name = result[0]

        self.chan.queue_bind(exchange=self.exchange,
                             queue=self.send_queue_name,
                             routing_key=".".join(("irc", self.bot.nickname, "send", "*")))

        self.chan.queue_bind(exchange=self.exchange,
                             queue=self.send_queue_name,
                             routing_key=".".join(("irc", self.bot.nickname, "action", "*")))

        self.chan.queue_bind(exchange=self.exchange,
                             queue=self.send_queue_name,
                             routing_key=".".join(("irc", self.bot.nickname, "presence")))


        self.add_consumer()

    def add_consumer(self):
        self.consumer_tags.append(self.chan.basic_consume(callback=self.handle_consume,
                                                          queue=self.send_queue_name))

    def handle_consume(self, raw_msg):
        try:
            key = raw_msg.delivery_info["routing_key"].decode("utf-8").split(u".")
            body = raw_msg.body.decode("utf-8")

            log.info("CONSUME: routing_key=%r body=%r", key, body)

            if raw_msg.properties["content_type"] == "application/json":
                self.handle_json_message(key, json.loads(body))
            elif raw_msg.properties["content_type"] == "text/plain":
                self.handle_plain_message(key, body)
            else:
                log.error("Message with unknown content type: %r", body)

        except Exception:
            log.exception("Exception in consume handler")

        raw_msg.channel.basic_ack(raw_msg.delivery_tag)

    def handle_json_message(self, key, msg):
        if not "user" in msg:
            msg["user"] = None

        if key[2] == "presence":
            self.irc_presence(msg["status"], msg["msg"])
        elif key[2] == "send":
            self.irc_send(key[3], msg["user"], msg["msg"])
        elif key[2] == "action":
            self.irc_action(key[3], msg["msg"])
        else:
            log.error("Unknown message type: %r %r", key[2], msg)

    def handle_plain_message(self, key, msg):
        if key[2] == "presence":
            self.irc_presence(msg, u"")
        elif key[2] == "send":
            self.irc_send(key[3], key[3], msg)
        elif key[2] == "action":
            self.irc_action(key[3], msg)
        else:
            log.error("Unknown message type: %r %r", key[2], msg)

    def remove_consumer(self):
        for tag in self.consumer_tags:
            self.chan.basic_cancel(tag)

    def irc_presence(self, status, msg):
        log.debug("PRESENCE: %r %r", status, msg)

        if status == "away":
            self.bot.away(msg.encode("UTF-8"))
        elif status == "online":
            self.bot.back()
        else:
            log.error("Received unknown status: %r", status)

    def irc_action(self, dest, msg):
        for chan_key in config["channels"]:
            dest = dest.replace(chan_key, config["channels"][chan_key])

        log.debug("ACTION: dest=%r msg=%r", dest, msg)

        self.bot.me(dest.encode("utf-8"), msg.encode("utf-8"))

    def irc_send(self, dest, user, msg):
        for chan_key in config["channels"]:
            dest = dest.replace(chan_key, config["channels"][chan_key])

        is_channel_user_msg = (user != None and
                               dest in config["channels"].values() and
                               user not in config["channels"].values())
        is_bot_user_msg = (user != None and
                           dest == self.bot.nickname and
                           user != self.bot.nickname)
        is_dest_unknown = (user == None and
                           dest == self.bot.nickname)

        log.debug("SEND: user=%r dest=%r msg=%r channel_user_msg=%r bot_user_msg=%r dest_unk=%r",
                  user, dest, msg, is_channel_user_msg, is_bot_user_msg, is_dest_unknown)

        if is_channel_user_msg:
            self.irc_send_msg(dest, u"{}: {}".format(user, msg))
        elif is_bot_user_msg:
            self.irc_send_msg(user, msg)
        elif is_dest_unknown:
            log.error("Message dest/user invalid: Discarding")
        else:
            self.irc_send_msg(dest, msg)

    def irc_send_msg(self, dest, msg):
        msg = msg.encode("utf-8")
        dest= dest.encode("utf-8")

        lines = msg.split("\n")
        send_at_a_time = 400

        # if we have multi-line content assume that each line doesn't hit the IRC server's limit
        if len(lines) > 1:
            send_at_a_time = None
        else:
            send_at_a_time = 400

        for line in lines:
            log.debug("SEND: dest=%r line=%r", dest, line)
            self.bot.msg(dest, line, send_at_a_time)

    def irc_send_notice(self, dest, msg):
        msg = msg.encode("utf-8")
        dest = dest.encode("utf-8")

        lines = msg.split("\n")

        for line in lines:
            log.debug("SEND: dest=%r line=%r", dest, line)
            self.bot.notice(dest, line)

    def user_flags(self, user, chan):
        """Return set of user flags"""

        # query
        if chan == self.bot.nickname:
            ops = set.union(*self.bot.ops.values())
            voices = set.union(*self.bot.voices.values())
        # channel
        else:
            ops = set(self.bot.ops[chan])
            voices = set(self.bot.voices[chan])

        flags = {
            [None, "op"][user in ops],
            [None, "voice"][user in voices]
        }

        flags.discard(None)

        return flags

    def irc_recvd(self, user, msg, chan, type):
        """Called whenever something was received from irc"""

        user, msg, chan, type = [ x.decode("utf-8") for x in (user, msg, chan, type) ]

        jmsg = json.dumps({
            "user" : user,
            "msg" : msg,
            "chan" : chan,
            "type" : type,
            "bot" : self.bot.nickname,
            "uflags" : list(self.user_flags(user, chan)),
        })
        log.debug("RECV: user=%r chan=%r msg=%r type=%r jmsg=%r", user, chan, msg, type, jmsg)

        amsg = amqp.Message(jmsg.encode("utf-8"))
        amsg.properties["content_type"] = u"application/json"
        amsg.properties["delivery_mode"] = 2
        amsg.properties["app_id"] = u"edi-irc"

        # query
        if chan == self.bot.nickname:
            masq_chan = chan
        # channel
        else:
            masq_chan = config["channel-aliases"][chan]

        key = u".".join((u"irc",
                        self.bot.nickname,
                        u"recv",
                        masq_chan))

        try:
            log.debug("PUBLISH: routing_key=%r msg=%r", key, amsg)

            self.chan.basic_publish(exchange=self.exchange,
                                    routing_key=key,
                                    msg=amsg)
        except Exception:
            log.exception("Exception while publishing message")

    def run(self):
        while self.chan.callbacks:
            try:
                self.chan.wait()
            except Exception:
                time.sleep(5)

    def close(self):
        try:
            self.conn.close()
        except IOError:
            log.exception("Error while closing amqp connection")

class NamesIRCClient(irc.IRCClient):
    def __init__(self, *args, **kwargs):
        self._namescallback = {}

    def names(self, channel):
        channel = channel.lower()
        d = defer.Deferred()
        if channel not in self._namescallback:
            self._namescallback[channel] = ([], [])

        self._namescallback[channel][0].append(d)
        self.sendLine("NAMES %s" % channel)
        return d

    def irc_RPL_NAMREPLY(self, prefix, params):
        channel = params[2].lower()
        nicklist = params[3].split(' ')

        if channel not in self._namescallback:
            return

        n = self._namescallback[channel][1]
        n += nicklist

    def irc_RPL_ENDOFNAMES(self, prefix, params):
        channel = params[1].lower()
        if channel not in self._namescallback:
            return

        callbacks, namelist = self._namescallback[channel]

        for cb in callbacks:
            cb.callback(namelist)

        del self._namescallback[channel]


class MQBot(NamesIRCClient):
    """http://twistedmatrix.com/documents/8.2.0/api/twisted.words.protocols.irc.IRCClient.html"""

    nickname = config["nick"]
    username = config["nick"]
    password = config["passwd"]
    realname = """Uh, my name's EDI, uh, I'm not an addict."""
    lineRate = 1.0

    ops = dict()
    voices = dict()

    def connectionMade(self):
        log.info("Connection established")
        irc.IRCClient.connectionMade(self)
        self.pub = MQ(self)
        self.pub.start()

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self, reason)
        self.pub.close()

    def signedOn(self):
        log.info("IRC: Signed on")

        self.msg("NickServ", "IDENTIFY {}".format(self.password))

        for chan in config["channels"].values():
            log.info("IRC: join chan: %s", chan)
            self.join(chan)

    def joined(self, chan):
        if chan in config["channels"].values():
            self.fetch_chan_ops(chan)

    def modeChanged(self, user, chan, do_set_modes, modes, users):
        log.debug("modeChanged: by_user=%r chan=%r users=%r modes=%r do_set_modes=%r",
                  user, chan, users, modes, do_set_modes)

        if chan not in config["channels"].values():
            return

        for (u, m) in zip(users, list(modes)):
            log.debug(("" if do_set_modes else "un") + "setting mode %r for user %r", m, u)

            if m == "o":
                try:
                    if do_set_modes:
                        self.ops[chan].add(u)
                    else:
                        self.ops[chan].remove(u)
                except KeyError:
                    pass
            elif m == "v":
                try:
                    if do_set_modes:
                        self.voices[chan].add(u)
                    else:
                        self.voices[chan].remove(u)
                except KeyError:
                    pass
            else:
                log.debug("modeChanged: unknown mode %r", m)
                continue

    def userLeft(self, user, chan):
        if chan in config["channels"].values():
            self.fetch_chan_ops(chan)

    def privmsg(self, user, chan, msg):
        log.debug("PRIVMSG: %r %r", user, chan)
        user = user.split('!', 1)[0]

        self.pub.irc_recvd(user, msg, chan, "privmsg")

    def action(self, user, chan, msg):
        user = user.split('!', 1)[0]

        self.pub.irc_recvd(user, msg, chan, "action")

    def fetch_chan_ops(self, chan):
        def parseOps(names):
            self.voices[chan] = set(( n[1:] for n in names
                if n.startswith("+")))
            self.ops[chan] = set(( n[1:] for n in names
                if n.startswith("@")))
        self.names(chan).addCallback(parseOps)

    def me(self, channel, action):
        """
        Strike a pose.

        @type channel: C{str}
        @param channel: The name of the channel to have an action on. If it
        has no prefix, C{'#'} will to prepended to it.
        @type action: C{str}
        @param action: The action to preform.
        """
        if channel[0] not in '&#!+': channel = '#' + channel
        self.ctcpMakeQuery(channel, [('ACTION', action)])

class BotFactory(protocol.ClientFactory):
    protocol = MQBot

    def clientConnectionLost(self, connector, reason):
        log.debug("IRC: connection lost: %r %r", connector, reason)
        log.error("IRC: reconnecting..")
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        log.error("IRC: connection failed: %r %r", connector, reason)
        reactor.stop()

def load_clicert(filename):
    with open(filename, "r") as fd:
        cert = ssl.PrivateCertificate.loadPEM(fd.read())
    return cert

def load_cacert(filename):
    with open(filename, "r") as fd:
        cert = ssl.Certificate.loadPEM(fd.read())
    return cert

def connect(factory):
    if config.has_key("ssl") and config["ssl"]:
        if config["ssl"] == "cert":
            log.info("CONNECT: SSL with client cert")

            cli = load_clicert(config["ssl_clicert"])
            ca = load_cacert(config["ssl_cacert"])

            log.info("Using client certificate:\n %s", cli.inspect())

            reactor.connectSSL(config["host"],
                               config["port"],
                               factory,
                               ssl.CertificateOptions(
                                   privateKey=cli.privateKey.original,
                                   certificate=cli.original,
                                   verify=True,
                                   caCerts=(ca.original,)))
        else:
            log.info("CONNECT: SSL default")
            reactor.connectSSL(config["host"],
                               config["port"],
                               factory,
                               ssl.ClientContextFactory())
    else:
        log.info("CONNECT: No SSL")
        reactor.connectTCP("irc.hackint.org",
                           6666,
                           factory)

def log_config():
    format = "{:s}={:s}"

    log.info("mqbot configuration: %s",
             ", ".join((format.format(k,repr(v))
                        for k,v in config.iteritems()
                        if k not in ["passwd"])))

if __name__ == '__main__':
    log_config()

    factory = BotFactory()
    connect(factory)

    reactor.run()
