#!/usr/bin/env python
# -*- coding: utf-8 -*-
__author__ = "space"

#shot url stuff

import edi
import json
import feedparser
import os
import re
import time
from threading import Thread

import logging
logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)

JSONED_MEMORY = os.path.abspath(os.getenv("EDI_RSS_FILE") or
                os.path.abspath(os.path.join(os.path.dirname(__file__), 'rss.json')))

if os.path.isfile(JSONED_MEMORY):
    MEMORY = json.load(open(JSONED_MEMORY, "rb"))
    log.debug(MEMORY)
else:
    MEMORY = dict()


def write_memory():
    with open(JSONED_MEMORY, "wb") as f:
        json.dump(MEMORY, f)

def publish(src, user, message):
    if user:
        edi.emit.msg_reply(e.chan,
                           src=src,
                           user=user,
                           msg=message)
    else:
        edi.emit.msg_reply(e.chan,
                           src=src,
                           msg=message)

def add_rss(src, user, alias, url):
    in_channel = src.split('.')[1] != src.split('.')[3]
    if in_channel: ident = src
    else: ident = user

    if not rss_check(url):
        to_send = "That url doesn't seem to be a valid RSS feed."
        publish(src, user, to_send)
        return

    if not MEMORY.has_key(ident):
        MEMORY[ident] = dict()

    if MEMORY[ident].has_key(alias):
        to_send = "%s? I already track that for you.." % (alias)
        publish(src, user, to_send)
    elif url in [v['url'] for v in MEMORY[ident].values()]:
        to_send = "I already track that url for you.."
        publish(src, user, to_send)
    else:
        MEMORY[ident][alias] = { 'src'           : src,
                                 'user'          : user,
                                 'url'           : url,
                                 'last_published': "" }

    write_memory()
    update()


def del_rss(src, user, alias):
    in_channel = src.split('.')[1] != src.split('.')[3]
    if in_channel: ident = src
    else: ident = user

    if not MEMORY.has_key(ident):
        to_send = "I don't even know you."
    elif MEMORY[ident].has_key(alias):
        MEMORY[ident].pop(alias)
        write_memory()
        to_send = "I won't track %s anymore." % (alias)
    else:
        to_send = "%s? .. What's that supposed to be?!" % (alias)

    publish(src, user, to_send)

def list_rss(src, user):
    in_channel = src.split('.')[1] != src.split('.')[3]
    if in_channel: ident = src
    else: ident = user

    if not MEMORY.has_key(ident):
        to_send = "I don't track any RSS feeds."
    elif [v['url'] for v in MEMORY[ident].values()] == []:
        to_send = "I don't track any RSS feeds."
    else:
        to_send = "I track: %s" % (", ".join(MEMORY[ident].keys()))

    publish(src, user, to_send)

def rss_check(url):
    try:
        feed = feedparser.parse(url)
        assert feed["bozo"] != 1 # bozo == 1 means, that the feed wasn't parsable.
        assert feed.entries[0].title
        assert feed.entries[0].link

        res = feed
    except:
        res = False

    return res

def update():
    for ident in MEMORY.keys():
        for alias in MEMORY[ident].keys():
            feed = rss_check(MEMORY[ident][alias]['url'])
            src = MEMORY[ident][alias]['src']
            in_channel = src.split('.')[1] != src.split('.')[3]
            if in_channel: user = None
            else: user = MEMORY[ident][alias]['user']

            if not feed:
                to_send = "Uh.. I couldn't get %s for you." % (alias)
                publish(src, user, to_send)
                MEMORY[ident][alias]['last_published'] = to_send
                continue

            link = feed.entries[0].link
            link = re.findall(r'.{1,400}', link) # TODO: wat?
            link = "\n".join(link)

            to_send = "%s - %s - %s" % (alias, feed.entries[0].title, link)
            if to_send == MEMORY[ident][alias]['last_published']:
                continue
            else:
                publish(src, user, to_send)
                MEMORY[ident][alias]['last_published'] = to_send

    write_memory()


class FeedUpdater(Thread):
    def __init__(self):
        Thread.__init__(self)
        self.daemon = True

    def run(self):
        while True:
            log.debug("Updating Feeds")
            update()
            time.sleep(3*60)


with edi.Manager(name="RSS", descr="RSS feed client.") as e:

    @edi.edi_cmd(e, "rss-sub",
                 args="TEXT",
                 descr="Track RSS feed")
    def add_rss_recv(**args):
        if len(args["args"].split()) == 2:
            add_rss(args["src"], args["user"], args["args"].split()[0], args["args"].split()[1])
        else:
            to_send = "Try it like this: !sub <alias> <url>"
            publish(args["src"], args["user"], to_send)

    @edi.edi_cmd(e, "rss-unsub",
                 args="TEXT",
                 descr="Un-Track RSS feed")
    def del_rss_recv(**args):
        if len(args["args"].split()) == 1:
            del_rss(args["src"], args["user"], args["args"].split()[0])
        else:
            to_send = "Try it like this: !unsub <alias>"
            publish(args["src"], args["user"], to_send)

    @edi.edi_cmd(e, "rss-list",
                 args="NONE",
                 descr="List tracked RSS feeds")
    def list_rss_recv(**args):
        list_rss(args["src"], args["user"])

    e.register_inspect_command()
    FeedUpdater().start()    
    e.run()
