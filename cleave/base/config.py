#  Copyright (c) 2020 KTH Royal Institute of Technology
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
import importlib.machinery as im
from pathlib import Path
from typing import Any, Mapping

from .logging import Logger


class ConfigError(Exception):
    pass


class ConfigWrapper:
    def __init__(self,
                 config_path: str,
                 cmd_line_overrides: Mapping[str, Any] = {},
                 defaults: Mapping[str, Any] = {}):
        """
        Helper class to wrap access to a config.py file containing
        configuration variables for the program.

        Parameters
        ----------
        config_path
            Path to the config script.

        cmd_line_overrides
            Overrides for config variables obtained from the command line.
            Config parameters defined here will always override the config file.

        defaults
            Mapping of fallback values for missing parameters.
        """
        self._log = Logger()

        # load the config into memory as a module to eval it
        self._config_path = Path(config_path).resolve()
        self._log.info(f'Loading configuration from {self._config_path}...')
        self._module = im.SourceFileLoader('config', str(self._config_path)) \
            .load_module('config')

        # get the dictionary of variables in the config file, skipping
        # everything that's "hidden"
        self._config = {k: v for k, v in vars(self._module).items()
                        if not k.startswith('_')}

        for k, v in cmd_line_overrides.items():
            self._config[k] = v

        self._defaults = dict(defaults)

    @property
    def config_path(self) -> str:
        return str(self._config_path)

    def get_parameter(self, k: str) -> Any:
        try:
            try:
                return self._config[k]
            except KeyError:
                return self._defaults[k]
        except KeyError:
            raise ConfigError(f'Missing required configuration '
                              f'parameter {k}!')

    def __getattr__(self, item: str):
        return self.get_parameter(item)
