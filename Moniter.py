import errno
import json
import logging
import os
import pickle
import platform
import random
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta
from subprocess import PIPE
from typing import List, Dict, Union

import selenium
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common import utils
from selenium.webdriver.remote.webelement import WebElement


class WebDriver:
    def __init__(self):
        self.username: str = ""
        self.password: str = ""
        self.wait_time: int = 0
        self.random_time_margin: int = 0
        self.email_notify: bool = False
        self.email_receivers: List[str] = []
        self.mail_host: str = ""
        self.mail_user: str = ""
        self.mail_pass: str = ""
        self.bark_notify: bool = False
        self.bark_api: str = ""

        chrome_options = Options()
        chrome_options.add_argument("--headless")  # 无窗口，若调试可以取消该选项
        chrome_options.add_argument("--disable-gpu")
        self.driver = webdriver.Chrome(options=chrome_options)
        self.previous_data = {}
        self.previous_score = {}

    def start_loop(self):
        """
        主循环
        """
        log.info("Load config...")
        self.load_config()
        log.info("Open Engrade...")
        self.driver.get("https://engradepro.com")
        while True:
            log.info("Load data...")
            self.load_data()
            need_login = True
            # noinspection PyUnresolvedReferences
            try:
                self.driver.find_element_by_name("usr")
            except selenium.common.exceptions.NoSuchElementException:
                # 已经在主页面
                need_login = False
            if need_login:
                log.info("Login...")
                self.login()
                log.info("Change course category...")
                if not self.change_course_category():
                    notify("Engrade Helper", "Not enrolled in any classes.")
                    log.critical("Not enrolled in any classes.")
                    return False
            c = self.get_course_list()
            change_list = []
            for i in range(len(c)):
                is_change = self.get_course_detail(c[i])
                # 这里需要更新Element列表，因为刷新页面后Element元素会变
                c = self.get_course_list()
                if is_change:
                    course = c[i][0].text
                    log.info("Change detected for {}!".format(course))
                    if len(c[i]) <= 2:
                        # 有一行没有成绩则列数为2
                        score = "NO SCORE"
                    else:
                        score = c[i][2].text
                    change_list.append((course, self.previous_score[course], score))
                else:
                    course = c[i][0].text
                    if len(c[i]) <= 2:
                        score = "NO SCORE"
                    else:
                        score = c[i][2].text
                    if course not in self.previous_score.keys():
                        self.previous_score[course] = score
                self.save_data()
            content: str = "Score change{} detected for {} course{} on Engrade.\n\n {}\n\nOpen in Engrade: {}".format(
                "" if len(change_list) == 1 else "s",
                len(change_list),
                "" if len(change_list) == 1 else "s",
                "\n".join("{}: {} -> {}".format(x[0], x[1], x[2]) for x in change_list),
                self.driver.current_url,
            )
            if change_list:
                notify(
                    "EngradeHelper",
                    content,
                    self.email_notify,
                    {
                        "email_receivers": self.email_receivers,
                        "mail_host": self.mail_host,
                        "mail_user": self.mail_user,
                        "mail_pass": self.mail_pass,
                    },
                    self.bark_notify,
                    self.bark_api,
                )
            wait = random.randint(
                self.wait_time - self.random_time_margin,
                self.wait_time + self.random_time_margin,
            )
            log.info("Waiting for {} seconds...".format(wait))
            time.sleep(wait)
            # 刷新页面，以防被登出
            self.driver.refresh()

    def load_config(self):
        """
        加载设置项
        """
        with open("config.json", "r") as file:
            setting = json.load(file)
        self.username = setting["Engrade"]["username"]
        self.password = setting["Engrade"]["password"]
        self.wait_time = setting["wait_time"]
        self.random_time_margin = setting["random_time_margin"]
        self.email_notify = setting["email_notification"]
        self.email_receivers = setting["email_receivers"]
        self.mail_host = setting["email_sender"]["smtp_host"]
        self.mail_user = setting["email_sender"]["address"]
        self.mail_pass = setting["email_sender"]["password"]
        self.bark_notify = setting["Bark_notification"]
        self.bark_api = setting["Bark_api"]

    def login(self):
        """
        登录操作
        """
        self.driver.find_element_by_name("usr").send_keys(self.username)
        self.driver.find_element_by_name("pwd").send_keys(self.password)
        self.driver.find_element_by_name("_submit").click()

    def load_data(self):
        """
        加载上一次的数据
        """
        if "data.cache" in os.listdir("."):
            with open("data.cache", "rb") as data:
                self.previous_data, self.previous_score = pickle.load(data)

    def change_course_category(self):
        """
        选择Course Period，目前自动选择SEMESTER
        """
        try:
            self.driver.find_element_by_xpath('//*[@id="gpselector"]/ul/li[1]').click()
        except selenium.common.exceptions.NoSuchElementException:
            return False
        for i in range(1, 30):
            course_xpath = '//*[@id="gpperiods"]/li[{}]'.format(i)
            # noinspection PyUnresolvedReferences
            try:
                c = self.driver.find_element_by_xpath(course_xpath)
            except selenium.common.exceptions.NoSuchElementException:
                break
            if "SEMESTER" in c.text:
                c.click()
                break
        return True

    def get_course_list(self) -> List[List[WebElement]]:
        """
        获取主界面上课程列表
        :return: [[CourseName, Teacher, Score], ...]
        """
        table = self.driver.find_element_by_xpath('//*[@id="classTable"]/tbody')
        courses = []
        for c in table.find_elements_by_tag_name("tr"):
            if not c.is_displayed():
                continue
            course_detail = c.find_elements_by_tag_name("a")
            courses.append(course_detail)
        return courses

    def get_course_detail(self, course: List[WebElement]) -> bool:
        """
        点进去单个课程比较详细内容。
        目前自动选择 Assignment 下的 Semester 类别
        :param course: 课程（get_course_list 的某个返回值）
        :return: 成绩是否改变
        """
        url = self.driver.current_url
        course_name = course[0].text
        log.debug("Get detail for {}...".format(course_name))
        course[0].click()

        # Navigate to semester detail
        self.driver.find_element_by_xpath('//*[@id="sideappgradebook"]/span[1]').click()
        self.driver.find_element_by_xpath('//*[@id="gpselector"]/ul/li[1]').click()
        self.driver.find_element_by_xpath('//*[@id="gpperiods"]/span[3]/a').click()

        detail = self.driver.find_element_by_xpath(
            '//*[@id="content-expanded"]/div[2]'
        ).get_attribute("outerHTML")
        is_change = False
        if course_name in self.previous_data.keys():
            if detail != self.previous_data[course_name]:
                is_change = True
        self.previous_data[course_name] = detail
        self.driver.get(url)
        return is_change

    def save_data(self):
        """
        保存数据
        """
        if "data.cache" not in os.listdir("."):
            open("data.cache", "w").close()
        with open("data.cache", "wb") as data:
            pickle.dump((self.previous_data, self.previous_score), data)


def notify(
        title: str,
        content: str,
        email_notify: bool = False,
        email_data: Dict[str, Union[str, List[str]]] = None,
        bark_notify: bool = False,
        bark_api: str = None,
):
    """
    发送通知，目前有三种形式：
    1. 发送系统通知，支持 win10(依赖于 win10toast) 和 macOS(未测试)
    2. 发送邮件通知，需要提供支持SMTP的邮箱服务（如126、qq等）
    3. 推送 Bark 通知，需要在手机上安装 bark 并提供 api 编号
    :param title: 通知标题
    :param content: 通知内容
    :param email_notify: 是否邮件通知
    :param email_data: 邮件通知具体设置
    :param bark_api: 是否 bark 推送消息
    :param bark_notify: bark 推送 api
    """
    if platform.system() == "Windows":
        try:
            while notifier.notification_active():
                ...
            notifier.show_toast(
                title, content.split("\n")[0], duration=10, threaded=True
            )
            log.debug("Show notification on Windows")
        except NameError:
            log.warning("Fail to show notification on Windows")
            pass
    elif platform.system() == "Darwin":
        # MacOS
        from subprocess import call

        cmd = 'display notification "{}" with title "{}"'.format(
            content.split("\n")[0], title
        )
        call(["osascript", "-e", cmd])
        log.info("Show notification on MacOS")

    if email_notify:
        import smtplib
        from email.mime.text import MIMEText
        from email.header import Header

        message = MIMEText(content, "plain", "utf-8")
        message["From"] = Header("Engrade Helper", "utf-8")
        message["To"] = Header("You <{}>".format(email_data["mail_user"]))
        message["Subject"] = Header(title, "utf-8")
        receivers = [email_data["email_receivers"]]
        smtp_obj = smtplib.SMTP()
        smtp_obj.connect(email_data["mail_host"], 25)
        smtp_obj.login(email_data["mail_user"], email_data["mail_pass"])
        smtp_obj.sendmail(email_data["mail_user"], receivers, message.as_string())
        log.debug("Email notify success")
    else:
        log.debug("Skip email notify")

    if bark_notify:
        from urllib.request import urlopen

        urlopen("https://api.day.app/{}/{}/{}".format(bark_api, title, content))


def start(self):
    """
    selenium Service 类中 start 方法的猴子补丁，
    用于隐藏 webdriver 控制台窗口
    """
    try:
        cmd = [self.path]
        cmd.extend(self.command_line_args())
        self.process = subprocess.Popen(
            cmd,
            env=self.env,
            close_fds=platform.system() != "Windows",
            stdout=self.log_file,
            stderr=self.log_file,
            stdin=PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,  # 取消显示窗口
        )
    except TypeError:
        raise
    except OSError as err:
        if err.errno == errno.ENOENT:
            raise WebDriverException(
                "'%s' executable needs to be in PATH. %s"
                % (os.path.basename(self.path), self.start_error_message)
            )
        elif err.errno == errno.EACCES:
            raise WebDriverException(
                "'%s' executable may have wrong permissions. %s"
                % (os.path.basename(self.path), self.start_error_message)
            )
        else:
            raise
    except Exception as e:
        raise WebDriverException(
            "The executable %s needs to be available in the path. %s\n%s"
            % (os.path.basename(self.path), self.start_error_message, str(e))
        )
    count = 0
    while True:
        self.assert_process_still_running()
        if self.is_connectable():
            break
        count += 1
        time.sleep(1)
        if count == 30:
            raise WebDriverException("Can not connect to the Service %s" % self.path)


def delete_old_log():
    """
    删除两天以上的 log
    """
    yesterday = "Log {}.log".format(str(datetime.today() - timedelta(1)).split()[0])
    today = "Log {}.log".format(str(datetime.today()).split()[0])

    for file in os.listdir("."):
        if file.endswith(".log") and file != yesterday and file != today:
            os.remove(file)


if __name__ == "__main__":
    log = logging.Logger("Logger", logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s: %(message)s")
    fh = logging.FileHandler("Log {}.log".format(str(datetime.today()).split()[0]))
    fh.setFormatter(formatter)
    fh.setLevel(logging.DEBUG)
    log.addHandler(fh)
    sh = logging.StreamHandler(__import__("sys").stdout)
    sh.setFormatter(formatter)
    log.addHandler(sh)

    if platform.system() == "Windows":
        try:
            from win10toast import ToastNotifier

            notifier = ToastNotifier()
        except ImportError:
            pass

    notify("EngradeHelper", "Start!")
    # noinspection PyUnresolvedReferences
    webdriver.common.service.Service.start = start
    w: WebDriver

    t = 0
    has_disconnected = False
    while True:
        t += 1
        fh = logging.FileHandler("Log {}.log".format(str(datetime.today()).split()[0]))
        delete_old_log()
        try:
            w = WebDriver()
            if not w.start_loop():
                break
        except selenium.common.exceptions.TimeoutException:
            log.warning("Timeout! Retry = " + str(t))
            notify("EngradeHelper", "Connection timeout. Retry = " + str(t))
            # noinspection PyUnboundLocalVariable
            w.driver.quit()
            if t >= 6:
                break
        except Exception as e:
            if has_disconnected:
                t = 1
            log.critical("Unknown Error!\n" + str(e))
            with open("EngradeHelper.log", "a") as f:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                traceback.print_tb(exc_traceback, file=f)
            notify(
                "EngradeHelper",
                "Unknown Error! Detail stored in log file, please report it on Github.",
            )
            notify("EngradeHelper", "Process end!")
            w.driver.quit()
            raise e
    notify("EngradeHelper", "Process end!")
    w.driver.quit()
