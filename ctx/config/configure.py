#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import json
import yaml
import requests
import socket
from datetime import datetime

# try:
#     from ..common.logger import CustomLog as CL
# except:
from common.logger import CustomLog as CL
from common import converter
from termcolor import cprint
import sys


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ipaddr = s.getsockname()[0]
    except Exception:
        ipaddr = '127.0.0.1'
    finally:
        s.close()
    return ipaddr


def singleton(class_):
    instances = {}

    def getinstance(*args, **kwargs):
        if class_ not in instances:
            instances[class_] = class_(*args, **kwargs)
        return instances[class_]
    return getinstance


@singleton
class Configure:
    def __init__(self, use_file=False):
        self.about = {}
        self.get_version()
        self.config = dict()
        self.second_env_dict = {
            "GOLOOP_BACKUP_DIR": "backup",
            "GOLOOP_EE_SOCKET": "ee.sock",
            "GOLOOP_NODE_SOCK": "cli.sock",
            "CPU_PROFILE": "cpu.profile",
            "MEM_PROFILE": "mem.profile"
        }
        self.compose_env = self._compose_env()
        self.log_dir = f"{self.compose_env['BASE_DIR']}/logs"
        if not os.path.isdir(self.log_dir):
            os.mkdir(self.log_dir)

        self.loggers = {'booting.log': self.init_logger('booting.log', log_level='debug', log_stdout=True)}
        self.logger = self.get_logger('booting.log')
        self.get_config(use_file)
        sys.excepthook = self.exception_handler

    def get_version(self):
        for version_info in ["VERSION", "BUILD_DATE", "VCS_REF"]:
            self.about[version_info] = os.getenv(version_info)
        return self.about

    def exception_handler(self, exception_type, exception, traceback):
        exception_string = f"[Exception] {exception_type.__name__}: {exception}, {traceback.tb_frame}"
        cprint(f"{exception_string}", "red")
        self.logger.error(f"{exception_string}")

    def get_logger(self, log_file="booting.log"):
        return self.loggers.get(log_file, self.loggers.get('booting.log')).log

    def init_logger(self, log_file=None, log_level='debug', log_stdout=False):
        logger = CL(log_file.upper())
        logger.set_level(log_level.upper())
        if log_stdout or self.config['settings']['env']['COMPOSE_ENV'].get('DOCKER_LOG_STDOUT', False) is True:
            logger.stream_handler(log_level.upper())
        logger.time_rotate_handler(
            filename=f"{self.log_dir}/{log_file}",
            when="midnight",
            backup_count=6,
            level=log_level.upper()
        )
        logger.set_level(log_level.upper())
        return logger

    def _compose_env(self, ):
        temp_env = dict()
        temp_env['CONFIG_URL'] = os.getenv('CONFIG_URL', 'https://networkinfo.solidwallet.io/icon2')
        temp_env['SERVICE'] = os.getenv('SERVICE', 'MainNet')
        temp_env['CONFIG_URL_FILE'] = os.getenv('CONFIG_URL_FILE', 'default_configure.yml')
        temp_env['CONFIG_LOCAL_FILE'] = os.getenv('CONFIG_LOCAL_FILE', '/goloop/configure.yml')
        temp_env['LOCAL_TEST'] = converter.str2bool(os.getenv('LOCAL_TEST', False))
        temp_env['BASE_DIR'] = os.getenv('BASE_DIR', '/goloop')
        return temp_env

    def get_config(self, use_file):
        service_url = f'{self.compose_env["CONFIG_URL"]}/{self.compose_env["SERVICE"]}'
        res = requests.get(f'{service_url}/{self.compose_env["CONFIG_URL_FILE"]}')

        if os.path.exists(self.compose_env['CONFIG_LOCAL_FILE']) or use_file:
            self.logger.info(f"Load config_from_file")
            self.config_from_file()
        else:
            self.logger.info(f"Download new configuration")
            if res.status_code == 200:
                self.config = yaml.load(res.text, Loader=yaml.FullLoader)
                if self.config.get('settings') and self.config['settings'].get('env'):
                    for compose_env in self.config['settings']['env'].get('COMPOSE_ENV', {}).keys():
                        if os.getenv(compose_env):
                            self.config['settings']['env'][compose_env] = self.get_os_env(compose_env)
                        else:
                            pass
                    self.config['settings']['env'].update(self.compose_env)
                    self.config['settings']['icon2'] = dict()
                    for icon2_env in self.config['reference'].get('icon2_default').keys():
                        if self.config['settings']['icon2'].get(icon2_env, None) is None:
                            self.config['settings']['icon2'][icon2_env] = self.get_os_env(icon2_env)
                    self.set_second_env(self.config['settings']['icon2']['GOLOOP_NODE_DIR'])
                    key_store_filename = self.config['settings']['env'].get("KEY_STORE_FILENAME", None)
                    if key_store_filename:
                        self.config['settings']['icon2']['GOLOOP_KEY_STORE'] = f"{self.config['settings']['env']['BASE_DIR']}/config/{key_store_filename}"
                    else:
                        self.config['settings']['icon2']['GOLOOP_KEY_STORE'] = os.getenv('GOLOOP_KEY_STORE')
                    if self.config['settings']['env'].get('GOLOOP_P2P'):
                        self.config['settings']['icon2']['GOLOOP_P2P'] = self.config['settings']['env']['GOLOOP_P2P']
                    elif self.compose_env['LOCAL_TEST'] is True:
                        private_ip = get_local_ip()
                        port = self.config['settings']['icon2'].get('GOLOOP_P2P_LISTEN', ':8080').split(':')[-1]
                        self.config['settings']['icon2']['GOLOOP_P2P'] = f"{private_ip}:{port}"
                        # self.logger.info(f"[LOCAL_TEST] GOLOOP_P2P = \"{private_ip}:{port}\"")
                    else:
                        public_ip = requests.get('http://checkip.amazonaws.com').text.strip()
                        port = self.config['settings']['icon2'].get('GOLOOP_P2P_LISTEN', ':8080').split(':')[-1]
                        self.config['settings']['icon2']['GOLOOP_P2P'] = f"{public_ip}:{port}"
                        # self.logger.info(f"[PUBLIC] GOLOOP_P2P = \"{public_ip}:{port}\"")
                        self.compose_env.pop('LOCAL_TEST')
                else:
                    self.logger.error('No env.')
            else:
                self.logger.error(f'API status code is {res.status_code}. ({service_url}/{self.compose_env["CONFIG_URL_FILE"]})')
        mig_info_file = self.config['settings']['env'].get('MIG_INFO_FILE', 'migration_configure.yml')
        mig_info_data_url = f"{service_url}/{mig_info_file}"
        res = requests.get(mig_info_data_url)
        if res.status_code == 200:
            self.config['settings']['mig'] = yaml.load(res.text, Loader=yaml.FullLoader)
        for mig_key in self.config['settings']['mig'].keys():
            if os.getenv(mig_key):
                self.config['settings']['mig'][mig_key] = self.get_os_env(mig_key)
        # self.logger.info(f"Initializing Configure\n{json.dumps(self.config['settings'], indent=4)}")

    def set_second_env(self, dir_name):
        for env_key, env_val in self.second_env_dict.items():
            if os.getenv(env_key) is not None:
                self.config['settings']['icon2'][env_key] = os.getenv(env_key)
            else:
                self.config['settings']['icon2'][env_key] = f"{os.path.join(dir_name, env_val)}"

    def get_os_env(self, env_key):
        if os.getenv(env_key) and os.getenv(env_key).lower() in ['true', 'false']:
            if os.getenv(env_key).lower() == 'true':
                return True
            else:
                return False
        else:
            return os.getenv(env_key, None)

    def config_from_file(self, ):
        try:
            base_dir = self.compose_env.get('BASE_DIR', '/goloop')
            file_name = f"{os.path.join(base_dir, self.compose_env.get('CONFIG_LOCAL_FILE', 'configure.yml'))}"
            with open(file_name, 'r') as js:
                self.config = yaml.load(js, Loader=yaml.FullLoader)
        except FileNotFoundError as e:
            print(e)

    def run(self, ):
        print(json.dumps(self.config, indent=4))


if __name__ == '__main__':
    CFG = Configure()
    CFG.run()
