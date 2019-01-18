import json
import os
import pickle
import random
import time
from typing import List, Dict, Union

import selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
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
        print("Load config...")
        self.load_config()
        print("Open Engrade...")
        self.driver.get("https://engradepro.com")
        while True:
            print("Load data...")
            self.load_data()
            need_login = True
            # noinspection PyUnresolvedReferences
            try:
                self.driver.find_element_by_name("usr")
            except selenium.common.exceptions.NoSuchElementException:
                # 已经在主页面
                need_login = False
            if need_login:
                print("Login...")
                self.login()
            print("Change course category...")
            self.change_course_category()
            c = self.get_course_list()
            change_list = []
            for i in range(len(c)):
                is_change = self.get_course_detail(c[i])
                # 这里需要更新Element列表，因为刷新页面后Element元素会变
                c = self.get_course_list()
                if is_change:
                    course = c[i][0].text
                    print("Change detected for {}!".format(course))
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
            content: str = "Score change{} detected for {} course{} on Engrade.\n\n {}\n\nOpen in Engrade: {}" \
                .format(
                "" if len(change_list) == 1 else "s",
                len(change_list),
                "" if len(change_list) == 1 else "s",
                "\n".join(
                    "{}: {} -> {}".format(x[0], x[1], x[2]) for x in change_list
                ),
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
                )
            print("Waiting...")
            wait = random.randint(
                self.wait_time - self.random_time_margin,
                self.wait_time + self.random_time_margin,
            )
            time.sleep(wait)
            # 刷新页面，以防被登出
            self.driver.refresh()
            print()

    def load_config(self):
        """
        加载设置项
        """
        with open("config.json", "r") as f:
            setting = json.load(f)
        self.username = setting["Engrade"]["username"]
        self.password = setting["Engrade"]["password"]
        self.wait_time = setting["wait_time"]
        self.random_time_margin = setting["random_time_margin"]
        self.email_notify = setting["email_notification"]
        self.email_receivers = setting["email_receivers"]
        self.mail_host = setting["email_sender"]["smtp_host"]
        self.mail_user = setting["email_sender"]["address"]
        self.mail_pass = setting["email_sender"]["password"]

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
            with open("data.cache", "rb") as f:
                self.previous_data, self.previous_score = pickle.load(f)

    def change_course_category(self):
        """
        选择Course Period，目前自动选择SEMESTER
        """
        self.driver.find_element_by_xpath('//*[@id="gpselector"]/ul/li[1]').click()
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
        print("Get detail for {}...".format(course_name))
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
                print(course_name + " changed!")
                is_change = True
        else:
            self.previous_data[course_name] = detail
        self.driver.get(url)
        return is_change

    def save_data(self):
        """
        保存数据
        """
        if "data.cache" not in os.listdir("."):
            open("data.cache", "w").close()
        with open("data.cache", "wb") as f:
            pickle.dump((self.previous_data, self.previous_score), f)


def notify(
        title: str,
        content: str,
        email_notify: bool = False,
        email_data: Dict[str, Union[str, List[str]]] = None,
):
    """
    发送通知，目前有两种形式：
    1. 发送系统通知，支持 win10(依赖于 win10toast) 和 macOS(未测试)
    2. 发送邮件通知，需要提供支持SMTP的邮箱服务（如126、qq等）
    :param title: 通知标题
    :param content: 通知内容
    :param email_notify: 是否邮件通知
    :param email_data: 邮件通知具体设置
    """
    import platform

    if platform.system() == "Windows":
        try:
            from win10toast import ToastNotifier

            ToastNotifier().show_toast(title, content, duration=10)
        except ImportError:
            pass
    elif platform.system() == "Darwin":
        # MacOS
        from subprocess import call

        cmd = 'display notification "{}" with title "{}"'.format(content, title)
        call(["osascript", "-e", cmd])

    if email_notify:
        import smtplib
        from email.mime.text import MIMEText
        from email.header import Header

        message = MIMEText(content, "plain", "utf-8")
        message["From"] = Header("Engrade Helper <autobox@test.com>", "utf-8")
        message["To"] = Header("You <{}>".format(email_data["mail_user"]))
        message["Subject"] = Header(title, "utf-8")
        receivers = [email_data["email_receivers"]]
        smtp_obj = smtplib.SMTP()
        smtp_obj.connect(email_data["mail_host"], 25)
        smtp_obj.login(email_data["mail_user"], email_data["mail_pass"])
        smtp_obj.sendmail(email_data["mail_user"], receivers, message.as_string())


if __name__ == "__main__":
    WebDriver().start_loop()
