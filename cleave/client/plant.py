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
#   limitations under the License.
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from multiprocessing import Event, Process, RLock
from typing import Any, Callable, Optional

from loguru import logger

from . import utils
from .actuator import BaseActuationCommand, BaseActuator
from .sensor import BaseSensor


class BaseState(ABC):
    @abstractmethod
    def advance(self,
                dt_ns: int,
                actuation: Optional[BaseActuationCommand] = None) \
            -> Any:
        pass


class Plant(Process):
    """
    Base class providing general functionality to represent closed-loop
    control plants.
    """

    def __init__(self,
                 dt_ns: int,
                 init_state: BaseState,
                 sensor: BaseSensor,
                 actuator: BaseActuator):
        """
        Parameters
        ----------
        dt
            Time interval in seconds between successive simulation steps.
        init_state
            Initial plant state.
        sensor
            BaseSensor instance associated with the plant.
        actuator
            BaseActuator instance associated with the plant.
        """
        super(Plant, self).__init__()
        logger.debug('Initializing plant.', enqueue=True)

        self._state = init_state
        self._state_lck = RLock()

        self._dt = dt_ns
        self._last_update = time.monotonic_ns()
        self._step_cnt = 0

        self._sensor = sensor
        self._actuator = actuator

        self._shutdown_event = Event()
        self._shutdown_event.set()

        # set up hooks
        self._start_of_step_hooks = utils.HookCollection()
        self._end_of_step_hooks = utils.HookCollection()
        self._pre_sim_hooks = utils.HookCollection()

    def hook_start_of_step(self, fn: Callable[[], ...]):
        """
        Register a callable to be called at the beginning of each simulation
        step. This callable should take no arguments.

        The intended use pattern for this method is as a decorator.

        Parameters
        ----------
        fn
            Callable to be invoked at the start of each simulation step.
        """
        self._start_of_step_hooks.add(fn)

    def hook_end_of_step(self, fn: Callable[[], ...]):
        """
        Register a callable to be called at the end of each simulation
        step. This callable should take no arguments.

        The intended use pattern for this method is as a decorator.

        Parameters
        ----------
        fn
            Callable to be invoked at the end of each simulation step.
        """
        self._end_of_step_hooks.add(fn)

    def hook_pre_sim(self, fn: Callable[[Any], ...]):
        """
        Register a callable to be called immediately before advancing the
        state of the simulation, but after the initial procedures of each
        simulation step. This callable should take an optional `actuation`
        keyword argument through which it will receive the actuation command
        about to be applied to the state.

        The intended use pattern for this method is as a decorator.

        Parameters
        ----------
        fn
            Callable to be invoked right before advancing the simulation state.
        """

        self._pre_sim_hooks.add(fn)

    def shutdown(self):
        """
        Shuts down this plant.
        """

        # TODO: might need to do more stuff here at some point
        logger.warning('Shutting down plant.', enqueue=True)
        self._shutdown_event.set()
        self._sensor.shutdown()
        self._actuator.shutdown()

    def sample_state(self) -> BaseState:
        """
        Returns the current state of the plant. Thread- and process-safe.

        Returns
        -------
        BaseState
            Current state of the plant.
        """
        with self._state_lck:
            return self._state

    def _step(self):
        """
        Executes all the necessary procedures to advance the simulation a
        single discrete time step. This method calls the respective hooks,
        polls the actuator, advances the state and updates the sensor.
        """
        self._start_of_step_hooks.call()

        # pull next actuation command from actuator
        actuation = self._actuator.get_next_actuation()
        self._pre_sim_hooks.call(actuation=actuation)

        sample = self._state.advance(
            dt_ns=time.monotonic_ns() - self._last_update,
            actuation=actuation
        )
        self._last_update = time.monotonic_ns()

        self._sensor.sample = sample
        self._end_of_step_hooks.call()
        self._step_cnt += 1

    def start(self) -> None:
        if self._shutdown_event.is_set():
            super(Plant, self).start()

    def run(self):
        """
        Executes the simulation loop.
        """
        self._shutdown_event.clear()
        try:
            logger.debug('Starting simulation', enqueue=True)
            utils.execute_periodically(
                fn=Plant._step,
                args=(self,),
                period_ns=self._dt,
                shutdown_flag=self._shutdown_event
            )
        except Exception as e:
            # TODO: descriptive exceptions
            logger.opt(exception=e).error('Caught exception!', enqueue=True)
            self.shutdown()
        finally:
            logger.debug('Finished simulation', enqueue=True)
