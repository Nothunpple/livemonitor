#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import time
import copy
import re
import threading
import requests
import json
from bs4 import BeautifulSoup
import lxml
from urllib.parse import quote


class Monitor(threading.Thread):
    # 初始化
    def __init__(self, name, tgt, tgt_name, cfg, **config_mod):
        super().__init__()
        self.name = name
        self.tgt = tgt
        self.tgt_name = tgt_name
        self.cfg = copy.deepcopy(cfg)
        for mod in config_mod:
            self.cfg[mod] = config_mod[mod]

        self.submonitor_config_name = "cfg"
        self.submonitor_threads = {}
        self.submonitor_cnt = 0
        self.submonitor_live_cnt = 0
        self.submonitor_checknow = False

        self.stop_now = False

    # 重设submonitorconfig名字并初始化
    def submonitorconfig_setname(self, submonitor_config_name):
        self.submonitor_config_name = submonitor_config_name
        try:
            submonitor_config = getattr(self, submonitor_config_name)
        except:
            submonitor_config = {"submonitor_dic": {}}
        setattr(self, self.submonitor_config_name, submonitor_config)

    # 向submonitorconfig添加预设的config
    def submonitorconfig_addconfig(self, config_name, config):
        submonitor_config = getattr(self, self.submonitor_config_name)
        submonitor_config[config_name] = config
        setattr(self, self.submonitor_config_name, submonitor_config)

    # 向submonitorconfig的submonitor_dic中添加子线程信息以启动子线程
    def submonitorconfig_addmonitor(self, monitor_name, monitor_class, monitor_target, monitor_target_name,
                                    monitor_config_name, **config_mod):
        submonitor_config = getattr(self, self.submonitor_config_name)
        if monitor_name not in submonitor_config["submonitor_dic"]:
            submonitor_config["submonitor_dic"][monitor_name] = {}
        submonitor_config["submonitor_dic"][monitor_name]["class"] = monitor_class
        submonitor_config["submonitor_dic"][monitor_name]["target"] = monitor_target
        submonitor_config["submonitor_dic"][monitor_name]["target_name"] = monitor_target_name
        submonitor_config["submonitor_dic"][monitor_name]["config_name"] = monitor_config_name
        for mod in config_mod:
            submonitor_config["submonitor_dic"][monitor_name][mod] = config_mod[mod]
        setattr(self, self.submonitor_config_name, submonitor_config)

    # 从submonitorconfig的submonitor_dic中删除对应的子线程
    def submonitorconfig_delmonitor(self, monitor_name):
        submonitor_config = getattr(self, self.submonitor_config_name)
        if monitor_name in submonitor_config["submonitor_dic"]:
            submonitor_config["submonitor_dic"].pop(monitor_name)
        setattr(self, self.submonitor_config_name, submonitor_config)

    # 按照submonitorconfig检查子线程池
    def checksubmonitor(self):
        if not self.submonitor_checknow:
            self.submonitor_checknow = True
            submonitorconfig = getattr(self, self.submonitor_config_name)
            if "submonitor_dic" in submonitorconfig:
                self.submonitor_cnt = len(submonitorconfig["submonitor_dic"])
                for monitor_name in submonitorconfig["submonitor_dic"]:
                    if monitor_name not in self.submonitor_threads:
                        # 按照submonitorconfig启动子线程并添加到子线程池
                        monitor_thread = createmonitor(monitor_name, submonitorconfig)
                        self.submonitor_threads[monitor_name] = monitor_thread

                self.submonitor_live_cnt = 0
                for monitor_name in list(self.submonitor_threads):
                    if monitor_name not in submonitorconfig["submonitor_dic"]:
                        # 按照submonitorconfig关闭子线程并清理子线程池
                        if self.submonitor_threads[monitor_name].is_alive():
                            self.submonitor_threads[monitor_name].stop()
                            self.submonitor_live_cnt += 1
                        else:
                            self.submonitor_threads.pop(monitor_name)
                    else:
                        # 从子线程池检查并重启
                        if self.submonitor_threads[monitor_name].is_alive():
                            self.submonitor_threads[monitor_name].checksubmonitor()
                            self.submonitor_live_cnt += 1
                        else:
                            self.submonitor_threads[monitor_name].stop()
                            monitor_thread = createmonitor(monitor_name, submonitorconfig)
                            self.submonitor_threads[monitor_name] = monitor_thread
                if self.submonitor_live_cnt > 0 or self.submonitor_cnt > 0:
                    printlog('[Check] "%s" 子线程运行情况：%s/%s' % (self.name, self.submonitor_live_cnt, self.submonitor_cnt))
            self.submonitor_checknow = False

    # 启动
    def run(self):
        self.checksubmonitor()
        while not self.stop_now:
            time.sleep(self.cfg["interval"])

    # 停止线程
    def stop(self):
        self.stop_now = True
        for monitor_name in self.submonitor_threads:
            self.submonitor_threads[monitor_name].stop()


# vip=tgt, word=title+description
class YoutubeLive(Monitor):
    def __init__(self, name, tgt, tgt_name, cfg, **config_mod):
        super().__init__(name, tgt, tgt_name, cfg, **config_mod)

        self.vip_dic = self.cfg["vip_dic"]
        self.word_dic = self.cfg["word_dic"]
        self.cookies = self.cfg["cookies"]
        self.logpath = './log/%s/%s.txt' % (self.__class__.__name__, self.name)
        if not os.path.exists('./log/%s' % self.__class__.__name__):
            os.mkdir('./log/%s' % self.__class__.__name__)

        # 重新设置submonitorconfig用于启动子线程，并添加频道id信息到子进程使用的cfg中
        self.submonitorconfig_setname("youtubechat_submonitor_cfg")
        self.submonitorconfig_addconfig("youtubechat_config", self.cfg)

        self.is_firstrun = True
        self.videodic = {}

    def run(self):
        while not self.stop_now:
            # 更新视频列表
            videodic_new = getyoutubevideodic(self.tgt)
            if isinstance(videodic_new, dict):
                for video_id in videodic_new:
                    if video_id not in self.videodic:
                        self.videodic[video_id] = videodic_new[video_id]
                        if not self.is_firstrun or videodic_new[video_id]["video_status"] == "进行" :
                            self.push(video_id)
                self.is_firstrun = False
                writelog(self.logpath, '[Success] "%s" getyoutubevideodic %s' % (self.name, self.tgt))
            else:
                printlog('[Error] "%s" getyoutubevideodic %s' % (self.name, self.tgt))
                writelog(self.logpath, '[Error] "%s" getyoutubevideodic %s' % (self.name, self.tgt))

            # 更新视频状态
            for video_id in self.videodic:
                if self.videodic[video_id]["video_status"] == "等待" or self.videodic[video_id]["video_status"] == "进行":
                    video_status = getyoutubevideostatus(video_id)
                    if video_status:
                        if self.videodic[video_id]["video_status"] != video_status:
                            self.videodic[video_id]["video_status"] = video_status
                            self.push(video_id)
                        writelog(self.logpath, '[Success] "%s" getyoutubevideostatus %s' % (self.name, video_id))
                    else:
                        printlog("[Error] %s getvideostatus %s" % (self.name, video_id))
                        writelog(self.logpath, '[Error] "%s" getyoutubevideostatus %s' % (self.name, video_id))
            time.sleep(self.cfg["interval"])

    def push(self, video_id):
        if self.videodic[video_id]["video_status"] == "等待" or self.videodic[video_id]["video_status"] == "进行" or \
                self.videodic[video_id]["video_type"] == "视频" and self.videodic[video_id]["video_status"] == "结束":

            # 获取视频简介
            video_description = getyoutubevideodescription(video_id)
            if isinstance(video_description, str):
                writelog(self.logpath,
                         '[Success] "%s" getyoutubevideodescription %s' % (self.name, video_id))
            else:
                printlog('[Error] "%s" getyoutubevideodescription %s' % (self.name, video_id))
                writelog(self.logpath, '[Error] "%s" getyoutubevideodescription %s' % (self.name, video_id))
                video_description = ""

            # 计算推送力度
            pushcolor_vipdic = getpushcolordic(self.tgt, self.cfg["vip_dic"])
            pushcolor_worddic = getpushcolordic("%s\n%s" % (self.videodic[video_id]["video_title"], video_description),
                                                self.cfg["word_dic"])
            pushcolor_dic = addpushcolordic(pushcolor_vipdic, pushcolor_worddic)

            # 进行推送
            if pushcolor_dic:
                pushtext = ""
                if self.videodic[video_id]["video_type"] == "直播":
                    if self.videodic[video_id]["video_status"] == "等待":
                        pushtext = "【%s %s 新直播间】\n标题：%s\n倒计时：%s\n网址：https://www.youtube.com/watch?v=%s" % (
                            self.__class__.__name__, self.tgt_name, self.videodic[video_id]["video_title"],
                            waittime(self.videodic[video_id]["video_timestamp"]), video_id)
                    elif self.videodic[video_id]["video_status"] == "进行":
                        pushtext = "【%s %s 直播开始】\n标题：%s\n网址：https://www.youtube.com/watch?v=%s" % (
                            self.__class__.__name__, self.tgt_name, self.videodic[video_id]["video_title"],
                            video_id)
                elif self.videodic[video_id]["video_type"] == "首播":
                    if self.videodic[video_id]["video_status"] == "等待":
                        pushtext = "【%s %s 新首播间】\n标题：%s\n倒计时：%s\n网址：https://www.youtube.com/watch?v=%s" % (
                            self.__class__.__name__, self.tgt_name, self.videodic[video_id]["video_title"],
                            waittime(self.videodic[video_id]["video_timestamp"]), video_id)
                    elif self.videodic[video_id]["video_status"] == "进行":
                        pushtext = "【%s %s 首播开始】\n标题：%s\n网址：https://www.youtube.com/watch?v=%s" % (
                            self.__class__.__name__, self.tgt_name, self.videodic[video_id]["video_title"],
                            video_id)
                elif self.videodic[video_id]["video_type"] == "视频":
                    pushtext = "【%s %s 上传视频】\n标题：%s\n网址：https://www.youtube.com/watch?v=%s" % (
                        self.__class__.__name__, self.tgt_name, self.videodic[video_id]["video_title"],
                        video_id)
                if pushtext:
                    pushall(pushtext, pushcolor_dic, self.cfg["push_dic"])
                    printlog('[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))
                    writelog(self.logpath,
                             '[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))
        # 开始记录弹幕
        if self.videodic[video_id]["video_status"] == "等待" or self.videodic[video_id]["video_status"] == "进行":
            monitor_name = "%s - YoutubeChat %s" % (self.name, video_id)
            if monitor_name not in getattr(self, self.submonitor_config_name)["submonitor_dic"]:
                self.submonitorconfig_addmonitor(monitor_name, "YoutubeChat", video_id, self.tgt_name,
                                                 "youtubechat_config", interval=4, tgt_channel=self.tgt)
                self.checksubmonitor()
                printlog('[Info] "%s" startsubmonitor %s' % (self.name, monitor_name))
                writelog(self.logpath, '[Info] "%s" startsubmonitor %s' % (self.name, monitor_name))
        # 停止记录弹幕
        else:
            monitor_name = "%s - YoutubeChat %s" % (self.name, video_id)
            if monitor_name in getattr(self, self.submonitor_config_name)["submonitor_dic"]:
                self.submonitorconfig_delmonitor(monitor_name)
                self.checksubmonitor()
                printlog('[Info] "%s" stopsubmonitor %s' % (self.name, monitor_name))
                writelog(self.logpath, '[Info] "%s" stopsubmonitor %s' % (self.name, monitor_name))


# vip=userchannel, word=text, punish=tgt+push
class YoutubeChat(Monitor):
    def __init__(self, name, tgt, tgt_name, cfg, **config_mod):
        super().__init__(name, tgt, tgt_name, cfg, **config_mod)

        self.vip_dic = self.cfg["vip_dic"]
        self.word_dic = self.cfg["word_dic"]
        self.cookies = self.cfg["cookies"]
        self.logpath = './log/%s/%s/%s.txt' % (
            self.__class__.__name__, self.tgt_name, self.name)
        if not os.path.exists('./log/%s' % self.__class__.__name__):
            os.mkdir('./log/%s' % self.__class__.__name__)
        if not os.path.exists('./log/%s/%s' % (self.__class__.__name__, self.tgt_name)):
            os.mkdir('./log/%s/%s' % (self.__class__.__name__, self.tgt_name))

        self.continuation = False
        self.pushpunish = {}
        self.tgt_channel = self.cfg["tgt_channel"]
        if self.tgt_channel in self.cfg["vip_dic"]:
            for color in self.cfg["vip_dic"][self.tgt_channel]:
                self.pushpunish[color] = self.cfg["vip_dic"][self.tgt_channel][color]

    def run(self):
        while not self.stop_now:
            # 获取continuation
            if not self.continuation:
                self.continuation = getyoutubechatcontinuation(self.tgt)
                if self.continuation:
                    writelog(self.logpath, '[Success] "%s" getyoutubechatcontinuation' % self.name)
                else:
                    printlog('[Error] "%s" getyoutubechatcontinuation' % self.name)
                    writelog(self.logpath, '[Error] "%s" getyoutubechatcontinuation' % self.name)
                    time.sleep(5)
                    continue

            # 获取直播评论列表
            if self.continuation:
                chatlist, self.continuation = getyoutubechatlist(self.continuation)
                if isinstance(chatlist, list):
                    for chat in chatlist:
                        writelog(self.logpath, "%s\t%s(%s)\t(%s)%s" % (
                            time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(chat["chat_timestamp"])),
                            chat["chat_username"], chat["chat_userchannel"], chat["chat_type"], chat["chat_text"]))
                        self.push(chat)
                else:
                    printlog('[Error] "%s" getyoutubechatlist %s' % (self.name, self.continuation))
                    writelog(self.logpath, '[Error] "%s" getyoutubechatlist %s' % (self.name, self.continuation))
            time.sleep(self.cfg["interval"])

    def push(self, chat):
        pushcolor_vipdic = getpushcolordic(chat["chat_userchannel"], self.cfg["vip_dic"])
        pushcolor_worddic = getpushcolordic(chat["chat_text"], self.cfg["word_dic"])
        pushcolor_dic = addpushcolordic(pushcolor_vipdic, pushcolor_worddic)
        
        if pushcolor_dic:
            # 只对pushcolor_dic存在的键进行修改，不同于addpushcolordic
            for color in self.pushpunish:
                if color in pushcolor_dic:
                    pushcolor_dic[color] -= self.pushpunish[color]

            pushtext = "【%s %s 直播评论】\n用户：%s\n内容：%s\n类型：%s\n网址：https://www.youtube.com/watch?v=%s" % (
                self.__class__.__name__, self.tgt_name, chat["chat_username"], chat["chat_text"], chat["chat_type"],
                self.tgt)
            pushall(pushtext, pushcolor_dic, self.cfg["push_dic"])
            printlog('[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))
            writelog(self.logpath, '[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))

            # 更新pushpunish
            for color in pushcolor_dic:
                if pushcolor_dic[color] > 0:
                    if color in self.pushpunish:
                        self.pushpunish[color] += 1
                    else:
                        self.pushpunish[color] = 1


# vip=tgt, word=text
class YoutubeCom(Monitor):
    def __init__(self, name, tgt, tgt_name, cfg, **config_mod):
        super().__init__(name, tgt, tgt_name, cfg, **config_mod)

        self.vip_dic = self.cfg["vip_dic"]
        self.word_dic = self.cfg["word_dic"]
        self.cookies = self.cfg["cookies"]
        self.logpath = './log/%s/%s.txt' % (self.__class__.__name__, self.name)
        if not os.path.exists('./log/%s' % self.__class__.__name__):
            os.mkdir('./log/%s' % self.__class__.__name__)

        self.is_firstrun = True
        self.postlist = []

    def run(self):
        while not self.stop_now:
            # 获取帖子列表
            postdic_new = getyoutubepostdic(self.tgt, self.cfg["cookies"])
            if isinstance(postdic_new, dict):
                for post_id in postdic_new:
                    if post_id not in self.postlist:
                        self.postlist.append(post_id)
                        if not self.is_firstrun:
                            self.push(post_id, postdic_new)
                writelog(self.logpath, '[Success] "%s" getyoutubepostdic %s' % (self.name, self.tgt))
                self.is_firstrun = False
            else:
                printlog('[Error] "%s" getyoutubepostdic %s' % (self.name, self.tgt))
                writelog(self.logpath, '[Error] "%s" getyoutubepostdic %s' % (self.name, self.tgt))
            time.sleep(self.cfg["interval"])

    def push(self, post_id, postdic):
        pushcolor_vipdic = getpushcolordic(self.tgt, self.cfg["vip_dic"])
        pushcolor_worddic = getpushcolordic(postdic[post_id]["post_text"], self.cfg["word_dic"])
        pushcolor_dic = addpushcolordic(pushcolor_vipdic, pushcolor_worddic)
        
        # 进行推送
        if pushcolor_dic:
            pushtext = "【%s %s 社区帖子】\n内容：%s\n时间：%s\n网址：https://www.youtube.com/post/%s" % (
                self.__class__.__name__, self.tgt_name, postdic[post_id]["post_text"][0:3000],
                postdic[post_id]["post_time"], post_id)
            pushall(pushtext, pushcolor_dic, self.cfg["push_dic"])
            printlog('[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))
            writelog(self.logpath, '[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))


# word=text
class YoutubeNote(Monitor):
    def __init__(self, name, tgt, tgt_name, cfg, **config_mod):
        super().__init__(name, tgt, tgt_name, cfg, **config_mod)

        self.vip_dic = self.cfg["vip_dic"]
        self.word_dic = self.cfg["word_dic"]
        self.cookies = self.cfg["cookies"]
        self.logpath = './log/%s/%s.txt' % (self.__class__.__name__, self.name)
        if not os.path.exists('./log/%s' % self.__class__.__name__):
            os.mkdir('./log/%s' % self.__class__.__name__)

        self.is_firstrun = True
        self.token = False
        self.notedic = {}

    def run(self):
        while not self.stop_now:
            # 获取token
            if not self.token:
                self.token = getyoutubetoken(self.cookies)
                if self.token:
                    writelog(self.logpath, '[Success] "%s" getyoutubetoken' % self.name)
                else:
                    printlog('[Error] "%s" getyoutubetoken' % self.name)
                    writelog(self.logpath, '[Error] "%s" getyoutubetoken' % self.name)
                    time.sleep(5)
                    continue

            # 获取订阅通知列表
            if self.token:
                notedic_new = getyoutubenotedic(self.token, self.cookies)
                if isinstance(notedic_new, dict):
                    for note_id in notedic_new:
                        if note_id not in self.notedic:
                            self.notedic[note_id] = notedic_new[note_id]
                            if not self.is_firstrun:
                                self.push(note_id)
                    self.is_firstrun = False
                    writelog(self.logpath, '[Success] "%s" getyoutubenotedic %s' % (self.name, self.tgt))
                else:
                    printlog('[Error] "%s" getyoutubenotedic %s' % (self.name, self.tgt))
                    writelog(self.logpath, '[Error] "%s" getyoutubenotedic %s' % (self.name, self.tgt))
            time.sleep(self.cfg["interval"])

    def push(self, note_id):
        pushcolor_worddic = getpushcolordic(self.notedic[note_id]["note_text"], self.cfg["word_dic"])
        pushcolor_dic = pushcolor_worddic
        
        if pushcolor_dic:
            pushtext = "【%s %s 订阅通知】\n内容：%s\n时间：%s\n网址：https://www.youtube.com/watch?v=%s" % (
                self.__class__.__name__, self.tgt_name, self.notedic[note_id]["note_text"],
                self.notedic[note_id]["note_time"], self.notedic[note_id]["note_videoid"])
            pushall(pushtext, pushcolor_dic, self.cfg["push_dic"])
            printlog('[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))
            writelog(self.logpath, '[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))


# vip=tgt
class TwitterUser(Monitor):
    def __init__(self, name, tgt, tgt_name, cfg, **config_mod):
        super().__init__(name, tgt, tgt_name, cfg, **config_mod)

        self.vip_dic = self.cfg["vip_dic"]
        self.word_dic = self.cfg["word_dic"]
        self.cookies = self.cfg["cookies"]
        self.logpath = './log/%s/%s.txt' % (self.__class__.__name__, self.name)
        if not os.path.exists('./log/%s' % self.__class__.__name__):
            os.mkdir('./log/%s' % self.__class__.__name__)

        self.is_firstrun = True
        self.userdata_dic = {}

    def run(self):
        while not self.stop_now:
            # 获取用户信息
            user_datadic_new = gettwitteruser(self.tgt, self.cookies)
            if isinstance(user_datadic_new, dict):
                pushtext_body = ""
                if self.is_firstrun:
                    self.userdata_dic = user_datadic_new
                    self.is_firstrun = False
                else:
                    for key in user_datadic_new:
                        # 不可能会增加新键所以不做判断
                        if self.userdata_dic[key] != user_datadic_new[key]:
                            pushtext_body += "键：%s\n原值：%s\n现值：%s\n\n" % (
                                key, str(self.userdata_dic[key]), str(user_datadic_new[key]))
                            self.userdata_dic[key] = user_datadic_new[key]
                writelog(self.logpath, '[Success] "%s" gettwitteruser' % self.name)

                if pushtext_body:
                    self.push(pushtext_body)
            else:
                printlog('[Error] "%s" gettwitteruser' % self.name)
                writelog(self.logpath, '[Error] "%s" gettwitteruser' % self.name)
            time.sleep(self.cfg["interval"])

    def push(self, pushtext_body):
        pushcolor_vipdic = getpushcolordic(self.tgt, self.cfg["vip_dic"])
        pushcolor_dic = pushcolor_vipdic
        
        if pushcolor_dic:
            pushtext = "【%s %s 数据改变】\n%s\n网址：https://twitter.com/%s" % (
                self.__class__.__name__, self.tgt_name, pushtext_body, self.tgt)
            pushall(pushtext, pushcolor_dic, self.cfg["push_dic"])
            printlog('[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))
            writelog(self.logpath, '[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))


# vip=tgt+mention, word=text
class TwitterTweet(Monitor):
    def __init__(self, name, tgt, tgt_name, cfg, **config_mod):
        super().__init__(name, tgt, tgt_name, cfg, **config_mod)

        self.vip_dic = self.cfg["vip_dic"]
        self.word_dic = self.cfg["word_dic"]
        self.cookies = self.cfg["cookies"]
        self.logpath = './log/%s/%s.txt' % (self.__class__.__name__, self.name)
        if not os.path.exists('./log/%s' % self.__class__.__name__):
            os.mkdir('./log/%s' % self.__class__.__name__)

        self.is_firstrun = True
        self.tgt_restid = False
        self.tweetlist = []

    def run(self):
        while not self.stop_now:
            # 获取用户restid
            if not self.tgt_restid:
                tgt_dic = gettwitteruser(self.tgt, self.cookies)
                if isinstance(tgt_dic, dict):
                    self.tgt_restid = tgt_dic["user_restid"]
                    writelog(self.logpath, '[Success] "%s" gettwitteruser' % self.name)
                else:
                    printlog('[Error] "%s" gettwitteruser' % self.name)
                    writelog(self.logpath, '[Error] "%s" gettwitteruser' % self.name)
                    time.sleep(5)
                    continue

            # 获取推特列表
            if self.tgt_restid:
                tweetdic_new = gettwittertweetdic(self.tgt_restid, self.cookies)
                if isinstance(tweetdic_new, dict):
                    for tweet_id in tweetdic_new:
                        if tweet_id not in self.tweetlist:
                            self.tweetlist.append(tweet_id)
                            if not self.is_firstrun:
                                self.push(tweet_id, tweetdic_new)
                    self.is_firstrun = False
                    writelog(self.logpath, '[Success] "%s" gettwittertweetdic' % self.name)
                else:
                    printlog('[Error] "%s" gettwittertweetdic' % self.name)
                    writelog(self.logpath, '[Error] "%s" gettwittertweetdic' % self.name)
            time.sleep(self.cfg["interval"])

    def push(self, tweet_id, tweetdic):
        # 获取用户推特时大小写不敏感，但检测用户和提及的时候大小写敏感
        pushcolor_vipdic = getpushcolordic("%s\n%s" % (self.tgt, tweetdic[tweet_id]['tweet_mention']),
                                           self.cfg["vip_dic"])
        pushcolor_worddic = getpushcolordic(tweetdic[tweet_id]['tweet_text'], self.cfg["word_dic"])
        pushcolor_dic = addpushcolordic(pushcolor_vipdic, pushcolor_worddic)
        
        if pushcolor_dic:
            pushtext = "【%s %s 推特%s】\n内容：%s\n媒体：%s\n时间：%s\n网址：https://twitter.com/%s/status/%s" % (
                self.__class__.__name__, self.tgt_name, tweetdic[tweet_id]["tweet_type"],
                tweetdic[tweet_id]["tweet_text"], tweetdic[tweet_id]["tweet_media"],
                time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(tweetdic[tweet_id]["tweet_timestamp"])), self.tgt,
                tweet_id)
            pushall(pushtext, pushcolor_dic, self.cfg["push_dic"])
            printlog('[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))
            writelog(self.logpath, '[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))


# vip=tgt+mention, word=text
class TwitterSearch(Monitor):
    def __init__(self, name, tgt, tgt_name, cfg, **config_mod):
        super().__init__(name, tgt, tgt_name, cfg, **config_mod)

        self.vip_dic = self.cfg["vip_dic"]
        self.word_dic = self.cfg["word_dic"]
        self.cookies = self.cfg["cookies"]
        self.logpath = './log/%s/%s.txt' % (self.__class__.__name__, self.name)
        if not os.path.exists('./log/%s' % self.__class__.__name__):
            os.mkdir('./log/%s' % self.__class__.__name__)

        self.is_firstrun = True
        self.tweetlist = []

    def run(self):
        while not self.stop_now:
            # 获取推特列表
            tweetdic_new = gettwittersearchdic(self.tgt, self.cookies)
            if isinstance(tweetdic_new, dict):
                for tweet_id in tweetdic_new:
                    if tweet_id not in self.tweetlist:
                        self.tweetlist.append(tweet_id)
                        if not self.is_firstrun:
                            self.push(tweet_id, tweetdic_new)
                self.is_firstrun = False
                writelog(self.logpath, '[Success] "%s" gettwittersearchdic' % self.name)
            else:
                printlog('[Error] "%s" gettwittersearchdic' % self.name)
                writelog(self.logpath, '[Error] "%s" gettwittersearchdic' % self.name)
            time.sleep(self.cfg["interval"])

    def push(self, tweet_id, tweetdic):
        pushcolor_vipdic = getpushcolordic("%s\n%s" % (self.tgt, tweetdic[tweet_id]['tweet_mention']),
                                           self.cfg["vip_dic"])
        pushcolor_worddic = getpushcolordic(tweetdic[tweet_id]['tweet_text'], self.cfg["word_dic"])
        pushcolor_dic = addpushcolordic(pushcolor_vipdic, pushcolor_worddic)
        
        if pushcolor_dic:
            pushtext = "【%s %s 推特%s】\n内容：%s\n媒体：%s\n时间：%s\n网址：https://twitter.com/a/status/%s" % (
                self.__class__.__name__, self.tgt_name, tweetdic[tweet_id]["tweet_type"],
                tweetdic[tweet_id]["tweet_text"], tweetdic[tweet_id]["tweet_media"],
                time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(tweetdic[tweet_id]["tweet_timestamp"])), tweet_id)
            pushall(pushtext, pushcolor_dic, self.cfg["push_dic"])
            printlog('[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))
            writelog(self.logpath, '[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))


# vip=tgt
class TwitcastLive(Monitor):
    def __init__(self, name, tgt, tgt_name, cfg, **config_mod):
        super().__init__(name, tgt, tgt_name, cfg, **config_mod)

        self.vip_dic = self.cfg["vip_dic"]
        self.word_dic = self.cfg["word_dic"]
        self.cookies = self.cfg["cookies"]
        self.logpath = './log/%s/%s.txt' % (self.__class__.__name__, self.name)
        if not os.path.exists('./log/%s' % self.__class__.__name__):
            os.mkdir('./log/%s' % self.__class__.__name__)

        # 重新设置submonitorconfig用于启动子线程，并添加频道id信息到子进程使用的cfg中
        self.submonitorconfig_setname("twitcastchat_submonitor_cfg")
        self.submonitorconfig_addconfig("twitcastchat_config", self.cfg)

        self.livedic = {}

    def run(self):
        while not self.stop_now:
            # 获取直播状态
            livedic_new = gettwitcastlive(self.tgt)
            if isinstance(livedic_new, dict):
                for live_id in livedic_new:
                    if live_id not in self.livedic or not livedic_new[live_id]:
                        for live_id_old in self.livedic:
                            if self.livedic[live_id_old]:
                                self.livedic[live_id_old] = False
                                self.push(live_id_old)
                    
                    if live_id not in self.livedic:
                        self.livedic[live_id] = livedic_new[live_id]
                        self.push(live_id)
                    elif self.livedic[live_id] != livedic_new[live_id]:
                        self.livedic[live_id] = livedic_new[live_id]
                        self.push(live_id)
                writelog(self.logpath, '[Success] "%s" gettwitcastlive' % self.name)
            else:
                printlog('[Error] "%s" gettwitcastlive' % self.name)
                writelog(self.logpath, '[Error] "%s" gettwitcastlive' % self.name)
            time.sleep(self.cfg["interval"])

    def push(self, live_id):
        if self.livedic[live_id]:
            pushcolor_vipdic = getpushcolordic(self.tgt, self.cfg["vip_dic"])
            pushcolor_dic = pushcolor_vipdic
            
            if pushcolor_dic:
                pushtext = "【%s %s TC开播】\n网址：https://twitcasting.tv/%s" % (
                    self.__class__.__name__, self.tgt_name, self.tgt)
                pushall(pushtext, pushcolor_dic, self.cfg["push_dic"])
                printlog('[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))
                writelog(self.logpath, '[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))

            # 开始记录弹幕
            monitor_name = "%s - TwitcastChat %s" % (self.name, live_id)
            if monitor_name not in getattr(self, self.submonitor_config_name)["submonitor_dic"]:
                self.submonitorconfig_addmonitor(monitor_name, "TwitcastChat", live_id, self.tgt_name,
                                                 "twitcastchat_config", interval=4, tgt_channel=self.tgt)
                self.checksubmonitor()
                printlog('[Info] "%s" startsubmonitor %s' % (self.name, monitor_name))
                writelog(self.logpath, '[Info] "%s" startsubmonitor %s' % (self.name, monitor_name))
        # 停止记录弹幕
        else:
            monitor_name = "%s - TwitcastChat %s" % (self.name, live_id)
            if monitor_name in getattr(self, self.submonitor_config_name)["submonitor_dic"]:
                self.submonitorconfig_delmonitor(monitor_name)
                self.checksubmonitor()
                printlog('[Info] "%s" stopsubmonitor %s' % (self.name, monitor_name))
                writelog(self.logpath, '[Info] "%s" stopsubmonitor %s' % (self.name, monitor_name))


# vip=chat_screenname, word=text, punish=tgt+push
class TwitcastChat(Monitor):
    def __init__(self, name, tgt, tgt_name, cfg, **config_mod):
        super().__init__(name, tgt, tgt_name, cfg, **config_mod)

        self.vip_dic = self.cfg["vip_dic"]
        self.word_dic = self.cfg["word_dic"]
        self.cookies = self.cfg["cookies"]
        self.logpath = './log/%s/%s.txt' % (self.__class__.__name__, self.name)
        if not os.path.exists('./log/%s' % self.__class__.__name__):
            os.mkdir('./log/%s' % self.__class__.__name__)

        self.chat_id_old = 0
        self.pushpunish = {}
        self.tgt_channel = self.cfg["tgt_channel"]
        if self.tgt_channel in self.cfg["vip_dic"]:
            for color in self.cfg["vip_dic"][self.tgt_channel]:
                self.pushpunish[color] = self.cfg["vip_dic"][self.tgt_channel][color]

    def run(self):
        while not self.stop_now:
            # 获取直播评论列表
            chatlist = gettwitcastchatlist(self.tgt)
            if isinstance(chatlist, list):
                for chat in chatlist:
                    if self.chat_id_old < chat['chat_id']:
                        self.chat_id_old = chat['chat_id']
                        writelog(self.logpath, "%s\t%s(%s)\t%s" % (
                            time.strftime('%Y-%m-%d %H:%M:%S',
                                          time.localtime(round(int(chat["chat_timestamp"]) / 1000))),
                            chat["chat_name"], chat["chat_screenname"], chat["chat_text"]))
                        self.push(chat)
            else:
                printlog('[Error] "%s" gettwitcastchatlist %s' % (self.name, self.chat_id_old))
                writelog(self.logpath, '[Error] "%s" gettwitcastchatlist %s' % (self.name, self.chat_id_old))
            time.sleep(self.cfg["interval"])

    def push(self, chat):
        pushcolor_vipdic = getpushcolordic(chat["chat_screenname"], self.cfg["vip_dic"])
        pushcolor_worddic = getpushcolordic(chat["chat_text"], self.cfg["word_dic"])
        pushcolor_dic = addpushcolordic(pushcolor_vipdic, pushcolor_worddic)
        
        if pushcolor_dic:
            # 只对pushcolor_dic存在的键进行修改，不同于addpushcolordic
            for color in self.pushpunish:
                if color in pushcolor_dic:
                    pushcolor_dic[color] -= self.pushpunish[color]

            pushtext = "【%s %s 直播评论】\n用户：%s(%s)\n内容：%s\n网址：https://twitcasting.tv/%s" % (
                self.__class__.__name__, self.tgt_name, chat["chat_name"], chat["chat_screenname"], chat["chat_text"],
                self.tgt_channel)
            pushall(pushtext, pushcolor_dic, self.cfg["push_dic"])
            printlog('[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))
            writelog(self.logpath, '[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))

            # 更新pushpunish
            for color in pushcolor_dic:
                if color in self.pushpunish:
                    self.pushpunish[color] += 1
                else:
                    self.pushpunish[color] = 1


# vip=tgt
class FanboxUser(Monitor):
    def __init__(self, name, tgt, tgt_name, cfg, **config_mod):
        super().__init__(name, tgt, tgt_name, cfg, **config_mod)

        self.vip_dic = self.cfg["vip_dic"]
        self.word_dic = self.cfg["word_dic"]
        self.cookies = self.cfg["cookies"]
        self.logpath = './log/%s/%s.txt' % (self.__class__.__name__, self.name)
        if not os.path.exists('./log/%s' % self.__class__.__name__):
            os.mkdir('./log/%s' % self.__class__.__name__)

        self.is_firstrun = True
        self.userdata_dic = {}

    def run(self):
        while not self.stop_now:
            # 获取用户信息
            user_datadic_new = getfanboxuser(self.tgt)
            if isinstance(user_datadic_new, dict):
                pushtext_body = ""
                if self.is_firstrun:
                    self.userdata_dic = user_datadic_new
                    self.is_firstrun = False
                else:
                    for key in user_datadic_new:
                        # 不可能会增加新键所以不做判断
                        if self.userdata_dic[key] != user_datadic_new[key]:
                            pushtext_body += "键：%s\n原值：%s\n现值：%s\n\n" % (
                                key, str(self.userdata_dic[key])[0:1300], str(user_datadic_new[key])[0:1300])
                            self.userdata_dic[key] = user_datadic_new[key]
                writelog(self.logpath, '[Success] "%s" getfanboxuser' % self.name)

                if pushtext_body:
                    self.push(pushtext_body)
            else:
                printlog('[Error] "%s" getfanboxuser' % self.name)
                writelog(self.logpath, '[Error] "%s" getfanboxuser' % self.name)
            time.sleep(self.cfg["interval"])

    def push(self, pushtext_body):
        pushcolor_vipdic = getpushcolordic(self.tgt, self.cfg["vip_dic"])
        pushcolor_dic = pushcolor_vipdic
        
        if pushcolor_dic:
            pushtext = "【%s %s 数据改变】\n%s\n网址：https://twitter.com/%s" % (
                self.__class__.__name__, self.tgt_name, pushtext_body, self.tgt)
            pushall(pushtext, pushcolor_dic, self.cfg["push_dic"])
            printlog('[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))
            writelog(self.logpath, '[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))


# vip=tgt, word=text
class FanboxPost(Monitor):
    def __init__(self, name, tgt, tgt_name, cfg, **config_mod):
        super().__init__(name, tgt, tgt_name, cfg, **config_mod)

        self.vip_dic = self.cfg["vip_dic"]
        self.word_dic = self.cfg["word_dic"]
        self.cookies = self.cfg["cookies"]
        self.logpath = './log/%s/%s.txt' % (self.__class__.__name__, self.name)
        if not os.path.exists('./log/%s' % self.__class__.__name__):
            os.mkdir('./log/%s' % self.__class__.__name__)

        self.is_firstrun = True
        self.postlist = []

    def run(self):
        while not self.stop_now:
            # 获取帖子列表
            postdic_new = getfanboxpostdic(self.tgt, self.cfg["cookies"])
            if isinstance(postdic_new, dict):
                for post_id in postdic_new:
                    if post_id not in self.postlist:
                        self.postlist.append(post_id)
                        if not self.is_firstrun:
                            self.push(post_id, postdic_new)
                writelog(self.logpath, '[Success] "%s" getfanboxpostdic %s' % (self.name, self.tgt))
                self.is_firstrun = False
            else:
                printlog('[Error] "%s" getfanboxpostdic %s' % (self.name, self.tgt))
                writelog(self.logpath, '[Error] "%s" getfanboxpostdic %s' % (self.name, self.tgt))
            time.sleep(self.cfg["interval"])

    def push(self, post_id, postdic):
        pushcolor_vipdic = getpushcolordic(self.tgt, self.cfg["vip_dic"])
        pushcolor_worddic = getpushcolordic(postdic[post_id]["post_text"], self.cfg["word_dic"])
        pushcolor_dic = addpushcolordic(pushcolor_vipdic, pushcolor_worddic)
        
        if pushcolor_dic:
            pushtext = "【%s %s 社区帖子】\n内容：%s\n类型：%s\n档位：%s\n时间：%s\n网址：https://www.pixiv.net/fanbox/creator/%s/post/%s" % (
                self.__class__.__name__, self.tgt_name, postdic[post_id]["post_text"][0:3000],
                postdic[post_id]["post_type"], postdic[post_id]['post_fee'],
                time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(postdic[post_id]["post_publishtimestamp"]))
                , self.tgt, post_id)
            pushall(pushtext, pushcolor_dic, self.cfg["push_dic"])
            printlog('[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))
            writelog(self.logpath, '[Info] "%s" pushall %s\n%s' % (self.name, str(pushcolor_dic), pushtext))


def getyoutubevideodic(user_id):
    try:
        videolist = {}
        url = "https://www.youtube.com/channel/%s/videos?view=57&flow=grid" % user_id
        response = requests.get(url, stream=True, timeout=(3, 7))
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'lxml')
            videolist_all = soup.find_all(class_='yt-lockup-content')
            for video in videolist_all:
                try:
                    video_id = video.h3.a["href"].replace('/watch?v=', '')
                    video_title = video.h3.a["title"]
                    if len(video.find(class_="yt-lockup-meta-info").find_all("li")) > 1:
                        video_type, video_status = "视频", "结束"
                        video_timestamp = round(time.time())
                    else:
                        timestamp = video.find(attrs={"data-timestamp": True})
                        if video.find(class_="accessible-description"):
                            if timestamp:
                                video_type, video_status = "首播", "等待"
                                video_timestamp = timestamp["data-timestamp"]
                            else:
                                video_type, video_status = "首播", "进行"
                                video_timestamp = round(time.time())
                        else:
                            if timestamp:
                                video_type, video_status = "直播", "等待"
                                video_timestamp = timestamp["data-timestamp"]
                            else:
                                video_type, video_status = "直播", "进行"
                                video_timestamp = round(time.time())
                    videolist[video_id] = {"video_title": video_title, "video_type": video_type,
                                           "video_status": video_status, "video_timestamp": video_timestamp}
                except:
                    pass
            # 可能为空 可以为空
            return videolist
        else:
            return False
    except:
        return False


def getyoutubevideostatus(video_id):
    try:
        url = 'https://www.youtube.com/heartbeat?video_id=%s' % video_id
        response = requests.get(url, stream=True, timeout=(3, 7))
        if response.status_code == 200:
            try:
                if response.json()["stop_heartbeat"] == 1:
                    video_status = "结束"
                    return video_status
                else:
                    # 测试中stop_heartbeat只在类型为视频的情况下出现且值为1
                    return False
            except:
                if response.json()["status"] == "stop":
                    video_status = "删除"
                elif response.json()["status"] == "ok":
                    video_status = "进行"
                elif "displayEndscreen" in response.json()["liveStreamability"]["liveStreamabilityRenderer"]:
                    video_status = "结束"
                else:
                    video_status = "等待"
                # 不可能为空 不可以为空
                return video_status
        else:
            return False
    except:
        return False


def getyoutubevideodescription(video_id):
    try:
        url = 'https://www.youtube.com/watch?v=%s' % video_id
        response = requests.get(url, stream=True, timeout=(3, 7))
        if response.status_code == 200:
            video_description = re.findall(r'\\"description\\":{\\"simpleText\\":\\"([^"]*)\\"', response.text)[0]
            video_description = eval('"""{}"""'.format(video_description))
            video_description = eval('"""{}"""'.format(video_description))
            # 可能为空 可以为空 区分空字符串
            return video_description
        else:
            return False
    except:
        return False


def getyoutubechatcontinuation(video_id):
    try:
        url = 'https://www.youtube.com/live_chat?is_popout=1&v=%s' % video_id
        headers = {
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.130 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=(3, 7))
        if response.status_code == 200:
            continuation = re.findall('"continuation":"([^"]*)"', response.text)[0]
            # 不可能为空 不可以为空
            return continuation
        else:
            return False
    except:
        return False


def getyoutubechatlist(continuation):
    try:
        chatlist = []
        url = "https://www.youtube.com/live_chat/get_live_chat"
        headers = {
            'authority': 'www.youtube.com',
            'x-youtube-device': 'cbr=Chrome&cbrver=79.0.3945.130&cosver=10.0&cos=Windows',
            'x-youtube-page-label': 'youtube.ytfe.desktop_20200116_5_RC0',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.130 Safari/537.36',
            'x-youtube-variants-checksum': '781368a49e2fe3e6fdf766601d0a3202',
            'x-youtube-page-cl': '290089588',
            'x-spf-referer': 'https://www.youtube.com/live_chat?continuation=' + continuation,
            'x-youtube-utc-offset': '480',
            'x-youtube-client-name': '1',
            'x-spf-previous': 'https://www.youtube.com/live_chat?continuation=' + continuation,
            'x-youtube-client-version': '2.20200116.05.00',
            'x-youtube-identity-token': 'QUFFLUhqbER4MFo0b1l6b0lNZXJyVk4yc1k3U09YazVPZ3w=',
            'x-youtube-ad-signals': 'dt=1579486488935&flash=0&frm=1&u_tz=480&u_his=3&u_java&u_h=864&u_w=1536&u_ah=824&u_aw=1536&u_cd=24&u_nplug=3&u_nmime=4&bc=31&bih=722&biw=1519&brdim=0%2C0%2C0%2C0%2C1536%2C0%2C1536%2C824%2C400%2C563&vis=2&wgl=true&ca_type=image',
            'accept': '*/*',
            'x-client-data': 'CKO1yQEIirbJAQimtskBCMG2yQEIqZ3KAQi9sMoBCPe0ygEIlrXKAQiZtcoBCOy1ygEI+7vKARirpMoB',
            'sec-fetch-site': 'same-origin',
            'sec-fetch-mode': 'cors',
            'referer': 'https://www.youtube.com/live_chat?continuation=' + continuation,
        }
        params = (
            ('commandMetadata', '[object Object]'),
            ('continuation', continuation),
            ('hidden', 'true'),
            ('pbj', '1'),
        )
        response = requests.get(url, headers=headers, params=params, timeout=(3, 7))
        if response.status_code == 200:
            continuation_new = re.findall('"continuation":"([^"]*)"', response.text)[0]
            chatlist_json = json.loads(response.text)['response']['continuationContents']['liveChatContinuation']
            if 'actions' in chatlist_json:
                for chat in chatlist_json['actions']:
                    try:
                        chat_dic = {}
                        if 'liveChatTextMessageRenderer' in chat['addChatItemAction']['item']:
                            chat_dic = chat['addChatItemAction']['item']['liveChatTextMessageRenderer']
                        elif 'liveChatPaidMessageRenderer' in chat['addChatItemAction']['item']:
                            chat_dic = chat['addChatItemAction']['item']['liveChatPaidMessageRenderer']
                        if chat_dic:
                            chat_timestamp = round(int(chat_dic['timestampUsec']) / 1000000)
                            chat_username = chat_dic['authorName']['simpleText']
                            chat_userchannel = chat_dic['authorExternalChannelId']
                            chat_type = ''
                            chat_text = ''
                            if 'message' in chat_dic:
                                chat_type = 'message'
                                for chat_text_run in chat_dic['message']['runs']:
                                    if 'text' in chat_text_run:
                                        chat_text += chat_text_run['text']
                                    elif 'emoji' in chat_text_run:
                                        chat_text += chat_text_run['emoji']['shortcuts'][0]
                            elif 'sticker' in chat_dic:
                                chat_type = 'supersticker'
                                chat_text = chat_dic['sticker']['accessibility']['accessibilityData']['label']
                            if 'purchaseAmountText' in chat_dic:
                                chat_type = 'superchat %s' % chat_dic['purchaseAmountText']['simpleText']
                            chatlist.append({"chat_timestamp": chat_timestamp, "chat_username": chat_username,
                                             "chat_userchannel": chat_userchannel, "chat_type": chat_type,
                                             "chat_text": chat_text})
                    except:
                        continue
            # 可能为空 可以为空
            return chatlist, continuation_new
        else:
            return False, continuation
    except:
        return False, continuation


def getyoutubepostdic(user_id, cookies):
    try:
        postlist = {}
        url = 'https://www.youtube.com/channel/%s/community' % user_id
        headers = {
            'authority': 'www.youtube.com',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.130 Safari/537.36',
        }
        response = requests.get(url, headers=headers, cookies=cookies, timeout=(3, 7))
        if response.status_code == 200:
            postpage_json = json.loads(re.findall('window\["ytInitialData"\] = (.*);', response.text)[0])
            postlist_json = postpage_json['contents']['twoColumnBrowseResultsRenderer']['tabs'][3]['tabRenderer'][
                'content']['sectionListRenderer']['contents'][0]['itemSectionRenderer']['contents']
            for post in postlist_json:
                try:
                    post_info = post['backstagePostThreadRenderer']['post']['backstagePostRenderer']
                    post_id = post_info['postId']
                    post_time = ''
                    for post_time_run in post_info['publishedTimeText']['runs']:
                        post_time += post_time_run['text']
                    post_text = ''
                    for post_text_run in post_info['contentText']['runs']:
                        post_text += post_text_run['text']
                    postlist[post_id] = {"post_time": post_time, "post_text": post_text}
                except:
                    pass
            # 可能为空 可以为空
            return postlist
        else:
            return False
    except:
        return False


def getyoutubetoken(cookies):
    try:
        headers = {
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.130 Safari/537.36'}
        response = requests.get('https://www.youtube.com', headers=headers, cookies=cookies)
        if response.status_code == 200:
            token = re.findall('"XSRF_TOKEN":"([^"]*)"', response.text)[0]
            return token
        else:
            return False
    except:
        return False


def getyoutubenotedic(token, cookies):
    try:
        youtubenotedic = {}
        headers = {
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.130 Safari/537.36'}
        params = (
            ('name', 'signalServiceEndpoint'),
            ('signal', 'GET_NOTIFICATIONS_MENU'),
        )
        data = {
            'sej': '{"clickTrackingParams":"CAkQovoBGAIiEwi9tvfcj5vnAhVUQ4UKHYyoBeQ=","commandMetadata":{"webCommandMetadata":{"url":"/service_ajax","sendPost":true,"apiUrl":"/youtubei/v1/notification/get_notification_menu"}},"signalServiceEndpoint":{"signal":"GET_NOTIFICATIONS_MENU","actions":[{"openPopupAction":{"popup":{"multiPageMenuRenderer":{"trackingParams":"CAoQ_6sBIhMIvbb33I-b5wIVVEOFCh2MqAXk","style":"MULTI_PAGE_MENU_STYLE_TYPE_NOTIFICATIONS","showLoadingSpinner":true}},"popupType":"DROPDOWN","beReused":true}}]}}',
            'session_token': token
        }
        response = requests.post('https://www.youtube.com/service_ajax', headers=headers, params=params,
                                 data=data, cookies=cookies, timeout=(3, 7))
        if response.status_code == 200:
            notelist_json = json.loads(response.text)['data']['actions'][0]['openPopupAction']['popup'][
                'multiPageMenuRenderer']['sections'][0]['multiPageMenuNotificationSectionRenderer']['items']
            for note in notelist_json:
                try:
                    if 'notificationRenderer' in note:
                        note_id = note['notificationRenderer']['notificationId']
                        note_text = note['notificationRenderer']['shortMessage']['simpleText']
                        note_time = note['notificationRenderer']['sentTimeText']['simpleText']
                        note_videoid = \
                            note['notificationRenderer']['navigationEndpoint']['commandMetadata']['webCommandMetadata'][
                                'url'].replace("/watch?v=", "")
                        youtubenotedic[note_id] = {"note_text": note_text, "note_time": note_time,
                                                   "note_videoid": note_videoid}
                except:
                    continue
            return youtubenotedic
        else:
            return False
    except:
        return False


def gettwitteruser(user_screenname, cookies):
    try:
        userdata_dic = {}
        headers = {
            'x-csrf-token': cookies['ct0'],
            'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.117 Safari/537.36',
        }
        params = (
            ('variables', '{"screen_name":"%s","withHighlightedLabel":false}' % user_screenname),
        )
        response = requests.get('https://api.twitter.com/graphql/G6Lk7nZ6eEKd7LBBZw9MYw/UserByScreenName',
                                headers=headers, params=params, cookies=cookies, timeout=(3, 7))
        if response.status_code == 200:
            user_data = response.json()['data']['user']
            userdata_dic["user_id"] = user_data['id']
            userdata_dic["user_restid"] = user_data['rest_id']
            userdata_dic["user_name"] = user_data['legacy']['name']
            userdata_dic["user_screenname"] = user_data['legacy']['screen_name']
            userdata_dic["user_description"] = user_data['legacy']['description']
            userdata_dic["user_entities"] = user_data['legacy']['entities']
            userdata_dic["user_location"] = user_data['legacy']['location']
            userdata_dic["user_profileimage"] = user_data['legacy']['profile_image_url_https']
            userdata_dic["user_bannerimage"] = user_data['legacy']['profile_banner_url']
            userdata_dic["user_twitcount"] = user_data['legacy']['statuses_count']
            userdata_dic["user_mediacount"] = user_data['legacy']['media_count']
            userdata_dic["user_favouritescount"] = user_data['legacy']['favourites_count']
            userdata_dic["user_friendscount"] = user_data['legacy']['friends_count']
            userdata_dic["user_wantretweet"] = user_data['legacy']['want_retweets']
            userdata_dic["user_protected"] = user_data['legacy']['protected']
            userdata_dic["user_candm"] = user_data['legacy']['can_dm']
            userdata_dic["user_canmediatag"] = user_data['legacy']['can_media_tag']
            userdata_dic["user_advertiseraccounttype"] = user_data['legacy']['advertiser_account_type']
            userdata_dic["user_pinnedtweetidsstr"] = user_data['legacy']['pinned_tweet_ids_str']
            userdata_dic["user_profileinterstitialtype"] = user_data['legacy']['profile_interstitial_type']
            userdata_dic["user_verified"] = user_data['legacy']['verified']
            userdata_dic["user_muting"] = user_data['legacy']['muting']
            return userdata_dic
        else:
            return False
    except:
        return False


def gettwittertweetdic(user_restid, cookies):
    try:
        tweet_dic = {}
        params = (
            ('include_profile_interstitial_type', '1'),
            ('include_blocking', '1'),
            ('include_blocked_by', '1'),
            ('include_followed_by', '1'),
            ('include_want_retweets', '1'),
            ('include_mute_edge', '1'),
            ('include_can_dm', '1'),
            ('include_can_media_tag', '1'),
            ('skip_status', '1'),
            ('cards_platform', 'Web-12'),
            ('include_cards', '1'),
            ('include_composer_source', 'true'),
            ('include_ext_alt_text', 'true'),
            ('include_reply_count', '1'),
            ('tweet_mode', 'extended'),
            ('include_entities', 'true'),
            ('include_user_entities', 'true'),
            ('include_ext_media_color', 'true'),
            ('include_ext_media_availability', 'true'),
            ('send_error_codes', 'true'),
            ('simple_quoted_tweets', 'true'),
            ('include_tweet_replies', 'true'),
            ('userId', user_restid),
            ('count', '20'),
            ('ext', 'mediaStats,cameraMoment')
        )
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:72.0) Gecko/20100101 Firefox/72.0',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
            'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-client-language': 'zh-cn',
            'x-twitter-active-user': 'yes',
            'x-csrf-token': cookies['ct0'],
            'Origin': 'https://twitter.com',
            'Connection': 'keep-alive',
            'TE': 'Trailers'
        }
        response = requests.get('https://api.twitter.com/2/timeline/profile/%s.json' % user_restid, headers=headers,
                                params=params, cookies=cookies, timeout=(3, 7))
        if response.status_code == 200:
            tweetlist_dic = response.json()['globalObjects']['tweets']
            for tweet_id in tweetlist_dic:
                try:
                    if tweetlist_dic[tweet_id]['user_id_str'] == user_restid:
                        tweet_timestamp = int(time.mktime(
                            time.strptime(tweetlist_dic[tweet_id]['created_at'], '%a %b %d %H:%M:%S %z %Y')))
                        tweet_text = tweetlist_dic[tweet_id]['full_text']
                        if 'retweeted_status_id_str' in tweetlist_dic[tweet_id]:
                            tweet_type = "转推"
                        elif 'user_mentions' in tweetlist_dic[tweet_id]['entities']:
                            tweet_type = "回复"
                        else:
                            tweet_type = "发布"
                        if 'media' in tweetlist_dic[tweet_id]['entities']:
                            tweet_media = "有"
                        else:
                            tweet_media = "无"
                        tweet_mention = ""
                        if 'user_mentions' in tweetlist_dic[tweet_id]['entities']:
                            for user_mention in tweetlist_dic[tweet_id]['entities']['user_mentions']:
                                tweet_mention += "%s\n" % user_mention['screen_name']
                        tweet_dic[tweet_id] = {"tweet_timestamp": tweet_timestamp, "tweet_text": tweet_text,
                                               "tweet_type": tweet_type, "tweet_media": tweet_media,
                                               "tweet_mention": tweet_mention}
                except:
                    continue
            return tweet_dic
        else:
            return False
    except:
        return False


def gettwittersearchdic(qword, cookies):
    try:
        tweet_dic = {}
        params = (
            ('include_profile_interstitial_type', '1'),
            ('include_blocking', '1'),
            ('include_blocked_by', '1'),
            ('include_followed_by', '1'),
            ('include_want_retweets', '1'),
            ('include_mute_edge', '1'),
            ('include_can_dm', '1'),
            ('include_can_media_tag', '1'),
            ('skip_status', '1'),
            ('cards_platform', 'Web-12'),
            ('include_cards', '1'),
            ('include_composer_source', 'true'),
            ('include_ext_alt_text', 'true'),
            ('include_reply_count', '1'),
            ('tweet_mode', 'extended'),
            ('include_entities', 'true'),
            ('include_user_entities', 'true'),
            ('include_ext_media_color', 'true'),
            ('include_ext_media_availability', 'true'),
            ('send_error_codes', 'true'),
            ('simple_quoted_tweets', 'true'),
            ('tweet_search_mode', 'live'),
            ('count', '20'),
            ('query_source', 'typed_query'),
            ('pc', '1'),
            ('spelling_corrections', '1'),
            ('ext', 'mediaStats,cameraMoment'),
        )
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:72.0) Gecko/20100101 Firefox/72.0',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
            'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-client-language': 'zh-cn',
            'x-twitter-active-user': 'yes',
            'x-csrf-token': cookies['ct0'],
            'Origin': 'https://twitter.com',
            'Connection': 'keep-alive',
            'TE': 'Trailers',
        }
        # 推文内容包括#话题标签的文字，filter:links匹配链接图片视频但不匹配#话题标签的链接，%%23相当于#话题标签
        url = 'https://api.twitter.com/2/search/adaptive.json?include_profile_interstitial_type=1&include_blocking=1&include_blocked_by=1&include_followed_by=1&include_want_retweets=1&include_mute_edge=1&include_can_dm=1&include_can_media_tag=1&skip_status=1&cards_platform=Web-12&include_cards=1&include_composer_source=true&include_ext_alt_text=true&include_reply_count=1&tweet_mode=extended&include_entities=true&include_user_entities=true&include_ext_media_color=true&include_ext_media_availability=true&send_error_codes=true&simple_quoted_tweets=true&q=' + qword + '&tweet_search_mode=live&count=20&query_source=typed_query&pc=1&spelling_corrections=1&ext=mediaStats%2CcameraMoment'
        response = requests.get(url, headers=headers, params=params, cookies=cookies, timeout=(3, 7))
        if response.status_code == 200:
            tweetlist_dic = response.json()['globalObjects']['tweets']
            for tweet_id in tweetlist_dic.keys():
                try:
                    tweet_timestamp = int(
                        time.mktime(time.strptime(tweetlist_dic[tweet_id]['created_at'], '%a %b %d %H:%M:%S %z %Y')))
                    tweet_text = tweetlist_dic[tweet_id]['full_text']
                    if 'retweeted_status_id_str' in tweetlist_dic[tweet_id]:
                        tweet_type = "转推"
                    # 不同于用户推特，总是有user_mentions键
                    elif tweetlist_dic[tweet_id]['entities']['user_mentions']:
                        tweet_type = "回复"
                    else:
                        tweet_type = "发布"
                    if 'media' in tweetlist_dic[tweet_id]['entities']:
                        tweet_media = "有"
                    else:
                        tweet_media = "无"
                    tweet_mention = ""
                    if tweetlist_dic[tweet_id]['entities']['user_mentions']:
                        for user_mention in tweetlist_dic[tweet_id]['entities']['user_mentions']:
                            tweet_mention += "%s\n" % user_mention['screen_name']
                    tweet_dic[tweet_id] = {"tweet_timestamp": tweet_timestamp, "tweet_text": tweet_text,
                                           "tweet_type": tweet_type, "tweet_media": tweet_media,
                                           "tweet_mention": tweet_mention}
                except:
                    continue
            return tweet_dic
        else:
            return False
    except:
        return False


def gettwitcastlive(user_id):
    try:
        live_dic = {}
        url = 'https://twitcasting.tv/streamserver.php?target=%s&mode=client' % user_id
        response = requests.get(url, timeout=(3, 7))
        if response.status_code == 200:
            try:
                live_dic[response.json()["movie"]["id"]] = response.json()["movie"]["live"]
                return live_dic
            except:
                live_dic = {"0": False}
                return live_dic
        else:
            return False
    except:
        return False


def gettwitcastchatlist(live_id):
    try:
        twitcastchatlist = []
        url = 'https://twitcasting.tv/userajax.php?c=listall&m=%s&n=10&f=0k=0&format=json' % live_id
        response = requests.get(url, timeout=(3, 7))
        if response.status_code == 200:
            for i in range(len(response.json()['comments'])):
                try:
                    chat = response.json()['comments'][i]
                    chat_id = chat['id']
                    chat_screenname = chat['author']['screenName']
                    chat_name = chat['author']['name']
                    chat_timestamp = chat['createdAt']
                    chat_text = chat['message']
                    twitcastchatlist.append(
                        {"chat_id": chat_id, "chat_screenname": chat_screenname, "chat_name": chat_name,
                         "chat_timestamp": chat_timestamp, "chat_text": chat_text})
                except:
                    continue
            return twitcastchatlist
        else:
            return False
    except:
        return False


def getfanboxuser(user_id):
    try:
        userdata_dic = {}
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.5",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
            "DNT": "1",
            "Host": "fanbox.pixiv.net",
            "Origin": "https://www.pixiv.net",
            "Referer": "https://www.pixiv.net/",
            "TE": "Trailers",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:73.0) Gecko/20100101 Firefox/73.0"
        }
        response = requests.get("https://fanbox.pixiv.net/api/creator.get?userId=%s" % user_id, headers=headers,
                                timeout=(3, 7))
        if response.status_code == 200:
            userdata_dic["user_id"] = response.json()["body"]["user"]["userId"]
            userdata_dic["user_name"] = response.json()["body"]["user"]["name"]
            userdata_dic["user_icon"] = response.json()["body"]["user"]["iconUrl"]
            userdata_dic["description"] = response.json()["body"]["description"]
            userdata_dic["coverimage"] = response.json()["body"]["coverImageUrl"]
            userdata_dic["description"] = response.json()["body"]["description"]
            userdata_dic["profilelinks"] = response.json()["body"]["profileLinks"]
            userdata_dic["hasboothshop"] = response.json()["body"]["hasBoothShop"]
            userdata_dic["hasadultcontent"] = response.json()["body"]["hasAdultContent"]
            userdata_dic["isstopped"] = response.json()["body"]["isStopped"]
            userdata_dic["hasadultcontent"] = response.json()["body"]["hasAdultContent"]
            return userdata_dic
        else:
            return False
    except:
        return False


def getfanboxpostdic(user_id, cookies):
    try:
        post_dic = {}
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.5",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
            "DNT": "1",
            "Host": "fanbox.pixiv.net",
            "Origin": "https://www.pixiv.net",
            "Referer": "https://www.pixiv.net/",
            "TE": "Trailers",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:73.0) Gecko/20100101 Firefox/73.0"
        }
        response = requests.get("https://fanbox.pixiv.net/api/post.listCreator?userId=%s&limit=10" % user_id,
                                headers=headers, cookies=cookies, timeout=(3, 7))
        if response.status_code == 200:
            post_list = response.json()['body']['items']
            for post in post_list:
                try:
                    post_id = post['id']
                    post_title = post['title']
                    post_publishtimestamp = round(
                        time.mktime(time.strptime(post['publishedDatetime'], "%Y-%m-%dT%H:%M:%S%z")))
                    post_type = post['type']
                    post_text = ""
                    if post['body']:
                        for block in post['body']['blocks']:
                            post_text += "%s\n" % block['text']
                    post_fee = post['feeRequired']
                    post_dic[post_id] = {"post_title": post_title, "post_publishtimestamp": post_publishtimestamp,
                                         "post_type": post_type, "post_text": post_text, "post_fee": post_fee}
                except:
                    continue
            return post_dic
        else:
            return False
    except:
        return False


# 检测推送力度
def getpushcolordic(text, dic):
    pushcolor_dic = {}
    for word in dic.keys():
        if text.count(word) > 0:
            for color in dic[word]:
                if color in pushcolor_dic:
                    pushcolor_dic[color] += int(dic[word][color])
                else:
                    pushcolor_dic[color] = int(dic[word][color])
    return pushcolor_dic


# 求和推送力度，注意传入subdics必须为tuple类型
def addpushcolordic(*adddics, **kwargs):
    pushcolor_dic = {}
    for adddic in adddics:
        for color in adddic.keys():
            if color in pushcolor_dic:
                pushcolor_dic[color] += adddic[color]
            else:
                pushcolor_dic[color] = adddic[color]
    if "subdics" in kwargs:
        for subdic in kwargs["subdics"]:
            for color in subdic.keys():
                if color in pushcolor_dic:
                    pushcolor_dic[color] -= subdic[color]
                else:
                    pushcolor_dic[color] = -subdic[color]
    return pushcolor_dic


# 全部推送
def pushall(pushtext, pushcolor_dic, config):
    pushqq(pushtext, pushcolor_dic, config["pushlist_qq"])
    return


# QQ推送
def pushqq(pushtext, pushcolor_dic, config):
    with open('./pause.json', 'r', encoding='utf-8') as f:
        pause = json.load(f)

    for qq in config:
        if qq["id"] in pause["pauseqq"]:
            pausepower = pause["pauseqq"][qq["id"]]
        else:
            pausepower = 0

        for color in qq["color_dic"]:
            if color in pushcolor_dic:
                if pushcolor_dic[color] - pausepower >= int(qq["color_dic"][color]):
                    pushtoqq_thread = threading.Thread(args=(pushtext, qq), target=pushtoqq)
                    pushtoqq_thread.start()
                    break


# QQ推送到账号
def pushtoqq(pushtext, qq):
    qq_type, qq_id, qq_port = qq["type"], qq["id"], qq["port"]
    # 不论windows还是linux都是127.0.0.1
    if qq_type == "user":
        url = 'http://127.0.0.1:%s/send_private_msg?user_id=%s&message=%s' % (qq_port, qq_id, quote(str(pushtext)))
    elif qq_type == "group":
        url = 'http://127.0.0.1:%s/send_group_msg?group_id=%s&message=%s' % (qq_port, qq_id, quote(str(pushtext)))
    else:
        return

    for retry in range(1, 10):
        status_code, status = "", ""
        try:
            response = requests.post(url, timeout=(3, 7))
            status_code = response.status_code
            status = response.json()['status']
        except:
            time.sleep(5)
        printlog('推送到QQ%s%s:%s，第%s次，结果%s:%s' % (qq_type, qq_id, qq_port, retry, status_code, status))
        if status == 'ok':
            return


def printlog(text):
    logtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    print("[%s] %s" % (logtime, text))
    return


def writelog(logpath, text):
    logtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    with open(logpath, 'a', encoding='utf-8') as log:
        log.write("[%s] %s\n" % (logtime, text))
    return


def waittime(timestamp):
    t = second_to_time(round(int(timestamp) - time.time()))
    return t


def second_to_time(seconds):
    d, seconds = divmod(seconds, 86400)
    h, seconds = divmod(seconds, 3600)
    m, s = divmod(seconds, 60)
    if d == 0:
        if h == 0:
            return "%s分%s秒" % (m, s)
        else:
            return "%s小时%s分%s秒" % (h, m, s)
    else:
        return "%s天%s小时%s分%s秒" % (d, h, m, s)


def createmonitor(monitor_name, config):
    monitor_class = config["submonitor_dic"][monitor_name]["class"]
    monitor_target = config["submonitor_dic"][monitor_name]["target"]
    monitor_target_name = config["submonitor_dic"][monitor_name]["target_name"]
    monitor_config = config[config["submonitor_dic"][monitor_name]["config_name"]]
    monitor_config_mod = {}
    for key in config["submonitor_dic"][monitor_name].keys():
        if key != "class" and key != "target" and key != "target_name" and key != "config_name":
            monitor_config_mod[key] = config["submonitor_dic"][monitor_name][key]
    monitor_thread = globals()[monitor_class](monitor_name, monitor_target, monitor_target_name, monitor_config,
                                              **monitor_config_mod)
    monitor_thread.start()
    return monitor_thread


if __name__ == '__main__':
    if not os.path.exists('./log'):
        os.makedirs('./log')

    # 读取配置文件
    config_name = input('默认为spider，不用输入json后缀名\n请输入配置文件名称：')
    while True:
        config_path = './%s.json' % (str(config_name))
        if not config_name:
            config_path = './spider.json'
            break
        if os.path.exists(config_path):
            break
        else:
            config_name = input('该配置文件不存在，请重新输入:')
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # 启动并监视主监视器
    monitor = Monitor("主线程", "main", "main", config)
    monitor.Daemon = True
    monitor.start()
    while True:
        time.sleep(60)
        monitor.checksubmonitor()