#!/usr/bin/env python
# -*- coding: utf-8 -*-
# ✓
#
# Twitter<->AMQP bot
#

from __future__ import unicode_literals
import sys
import time
import json
from threading import Thread
from amqplib import client_0_8 as amqp

import tweepy
from tweepy import StreamListener, OAuthHandler, Stream
from config import AMQP_SERVER, config

import logging

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger("twitter-bot")



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
                             routing_key=".".join(("twitter", self.bot.nickname, "send", "*")))


        self.add_consumer()

    def add_consumer(self):
        self.consumer_tags.append(self.chan.basic_consume(callback=self.handle_consume,
                                                          queue=self.send_queue_name))

    def handle_consume(self, raw_msg):
        try:
            key = raw_msg.delivery_info["routing_key"].split(".")
            body = raw_msg.body

            log.info("CONSUME: routing_key=%r body=%r", key, body)

            if raw_msg.properties["content_type"] == "application/json":
                self.handle_json_message(key, json.loads(body))
            elif raw_msg.properties["content_type"] == "text/plain":
                self.handle_plain_message(key, body)
            else:
                log.error("Message with unknown content type: %r", body)

        except Exception, e:
            log.exception("Exception in consume handler")

        raw_msg.channel.basic_ack(raw_msg.delivery_tag)


    def handle_json_message(self, key, msg):
        if key[2] == "send":
            self.twitter_send(msg["msg"], msg["user"], key[3])
        else:
            log.error("Unknown message type: %r %r", key[2], msg)

    def handle_plain_message(self, key, msg):
        if key[2] == "send":
            self.twitter_send(msg, None, key[3])
        else:
            log.error("Unknown message type: %r %r", key[2], msg)

    def remove_consumer(self):
        for tag in self.consumer_tags:
            self.chan.basic_cancel(tag)

    def user_flags(self, user_id):
        """Return set of user flags"""
        # Friend is what people one follows are called in the twitter api.

        flags = list()

        flags = {
            [None, "following"][user_id in self.bot.friends],
            [None, "follower"][user_id in self.bot.followers]
        }

        flags.discard(None)

        return flags

    def twitter_send(self, msg, user, target):
        if target == 'timeline' and user is not None:
            msg = "@%s: %s" % (user, msg)
        if len(msg) <= 140:
            if target == 'timeline':
                self.bot.tweet(msg)
            elif target == self.bot.nickname:
                if user is not None:
                    self.bot.pm(msg, user)
                else:
                    log.warning("Dropped '%s'. You can't send PMs as plaintest.", msg)
            else:
                log.warning("Dropped '%s'. Invalid target.", msg)
        else:
            log.warning("msg lenght > 140: %s", msg)

        log.debug("SEND: msg=%r", msg)

    def twitter_recvd(self, sender_nick, sender_id, msg, chan, type):
        """Called whenever something was received from twitter"""

        uflags = list(self.user_flags(sender_id))

        jmsg = json.dumps({
            "user" : sender_nick,
            "msg" : msg,
            "chan" : chan,
            "type" : type,
            "bot" : self.bot.nickname,
            "uflags" : uflags,
        })

        log.debug("RECV: sender_nick=%r, uflags=%r, msg=%r", sender_nick, uflags, msg)

        amsg = amqp.Message(jmsg)
        amsg.properties["content_type"] = "application/json"
        amsg.properties["delivery_mode"] = 2
        amsg.properties["app_id"] = "edi-twitter"

        routing_key = ".".join(("twitter",
                        self.bot.nickname,
                        "recv",
                        chan))

        try:
            log.debug("PUBLISH: routing_key=%r msg=%r", routing_key, amsg)

            self.chan.basic_publish(exchange=self.exchange,
                                    routing_key=routing_key,
                                    msg=amsg)
        except Exception, e:
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
        except IOError, e:
            log.exception("Error while closing amqp connection")

# Loop, that updates the friend list every 10 min
class FriendsUpdater(Thread):
    def __init__(self, bot):
        Thread.__init__(self)
        self.daemon = True
        self.bot = bot

    def run(self):
        while True:
            log.debug("Updating friends list")
            self.bot.friends = self.bot.api.friends_ids(self.bot.nickname)
            self.bot.followers = self.bot.api.followers_ids(self.bot.nickname)
            time.sleep( (10 * 60) )


class TwitterBot(StreamListener):

    def __init__(self):
        StreamListener.__init__(self)

        self.auth = self.authenticate()
        self.api = tweepy.API(self.auth)
        self.nickname = self.api.me().screen_name
        self.friends = self.api.friends_ids(self.nickname)
        self.followers = self.api.followers_ids(self.nickname)

        FriendsUpdater(self).start()
        self.blocking_connect(self.auth)

    consumer_key = config["consumer_key"]
    consumer_secret = config["consumer_secret"]
    access_token = config["access_token"]
    access_token_secret = config["access_token_secret"]
    auth = None
    api = None
    pub = None

    nickname = None
    friends = list()

    def on_direct_message(self, pm):
        sender_nick = pm.direct_message["sender"]["screen_name"]
        sender_id = pm.direct_message["sender"]["id"]
        pm_msg = pm.direct_message["text"]
        chan = self.nickname
        type = 'privmsg'

        log.debug(chan + ':\t' + pm_msg)
        self.pub.twitter_recvd(sender_nick, sender_id, pm_msg, chan, type)
        return True

    def on_status(self, tweet):
        sender_nick = tweet.author.screen_name
        sender_id = tweet.author.id
        tweet_msg = tweet.text
        chan = 'timeline'
        type = 'timeline'

        log.debug(chan + ':\t' + tweet_msg)
        self.pub.twitter_recvd(sender_nick, sender_id, tweet_msg, chan, type)
        return True

    def on_error(self, status_code):
        log.error('Got an error with status code: ' + str(status_code))
        return False # Don't continue listening
 
    def on_timeout(self):
        log.error('Timeout...')
        return False

    def tweet(self, msg):
        try:
            self.api.update_status(msg)
        except Exception, e:
            log.warning(e[0])

    def pm(self, msg, user):
        try:
            self.api.send_direct_message(screen_name = user, text = msg)
        except Exception, e:
            log.warning(e[0])

    def authenticate(self):
        auth = OAuthHandler(self.consumer_key, self.consumer_secret)
        auth.set_access_token(self.access_token, self.access_token_secret)
        return auth
 
    def blocking_connect(self, auth):
        log.info("CONNECT")

        for tries in xrange(1,5):
            self.pub = MQ(self)
            self.pub.start()

            twitterStream = Stream(auth, self) 
            twitterStream.userstream("with=following")
            log.warning("Reconnecting %i/4 ...", tries)

            self.pub.close()

        log.error("Giving up...")
        sys.exit(-1)


if __name__ == '__main__':
    TwitterBot()

