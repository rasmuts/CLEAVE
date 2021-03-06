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
from __future__ import annotations

import abc
import threading
from collections import namedtuple
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, NamedTuple, Sequence, Set, Union

import numpy as np
import pandas as pd

from ..logging import Logger


class Recorder(abc.ABC):
    def __init__(self, recordable: Recordable):
        recordable.recorders.add(self)

    @abc.abstractmethod
    def notify(self, latest_record: NamedTuple):
        pass

    def initialize(self):
        pass

    def shutdown(self):
        pass

    def flush(self):
        pass


class Recordable(abc.ABC):
    @property
    @abc.abstractmethod
    def recorders(self) -> Set[Recorder]:
        pass

    @property
    @abc.abstractmethod
    def record_fields(self) -> Sequence[str]:
        pass


class NamedRecordable(Recordable):
    def __init__(self,
                 name: str,
                 record_fields: Sequence[str],
                 opt_record_fields: Mapping[str, Any] = {}):
        self._name = name
        all_record_fields = list(record_fields) + list(opt_record_fields.keys())
        self._record_cls = namedtuple('_Record', all_record_fields,
                                      defaults=opt_record_fields.values())
        self._record_fields = self._record_cls._fields
        self._recorders: Set[Recorder] = set()

    @property
    def record_fields(self) -> Sequence[str]:
        return self._record_fields

    def push_record(self, **kwargs) -> None:
        record = self._record_cls(**kwargs)
        for recorder in self._recorders:
            recorder.notify(record)

    @property
    def recorders(self) -> Set[Recorder]:
        return self._recorders


class CSVRecorder(Recorder):
    def __init__(self,
                 recordable: Recordable,
                 output_path: Union[Path, str],
                 chunk_size: int = 1000):
        super(CSVRecorder, self).__init__(recordable)

        self._recordable = recordable
        self._log = Logger()

        self._path = output_path.resolve() \
            if isinstance(output_path, Path) else Path(output_path).resolve()

        if self._path.exists():
            if self._path.is_dir():
                raise FileExistsError(f'{self._path} exists and is a '
                                      f'directory!')
            self._log.warn(f'{self._path} will be overwritten with new data.')

        dummy_data = np.empty((chunk_size, len(recordable.record_fields)))
        self._table_chunk = pd.DataFrame(data=dummy_data,
                                         columns=recordable.record_fields)
        self._chunk_count = 0
        self._chunk_row_idx = 0

        self._lock = RLock()

    def initialize(self) -> None:
        # "touch" the file to clear it and prepare for actual writing
        with self._path.open('wb') as fp:
            fp.write(bytes(0x00))

    def _flush_chunk_to_disk(self) -> threading.Thread:
        chunk = self._table_chunk.iloc[:self._chunk_row_idx].copy()
        count = self._chunk_count

        def _flush():
            # TODO: make sure there's not a bottleneck in the flush
            #  operation, enqueue them somehow using a worker thread maybe.
            with self._lock, self._path.open('a', newline='') as fp:
                chunk.to_csv(fp, header=(count == 0), index=False)

        # flush in separate thread to avoid locking up the GIL
        t = threading.Thread(target=_flush)
        t.start()

        self._chunk_row_idx = 0
        self._chunk_count += 1

        return t

    def flush(self) -> None:
        self._flush_chunk_to_disk()

    def notify(self, latest_record: NamedTuple) -> None:
        self._table_chunk.iloc[self._chunk_row_idx] = \
            pd.Series(latest_record._asdict())
        self._chunk_row_idx += 1

        if self._chunk_row_idx == self._table_chunk.shape[0]:
            # flush to disk
            self._flush_chunk_to_disk()

    def shutdown(self) -> None:
        self._log.info(f'Flushing and closing CSV table writer on path '
                       f'{self._path}...')
        self._flush_chunk_to_disk().join()  # wait for the final write
