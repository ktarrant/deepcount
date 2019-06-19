import logging
import datetime
import os
from collections import OrderedDict

from transitions import Machine

from ibapi.common import BarData
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract

logger = logging.getLogger(__name__)


class SnapshotWriter:

    BAR_COLUMNS = [
        "date", "open", "high", "low", "close", "volume",
        # "barCount", "average",
    ]

    def __init__(self, ticker : str, base_dir = "snapshots"):
        self.ticker = ticker
        self.base_dir = base_dir
        self.cur_date = None
        self.cur_file = None

    def save_bar(self, bar : BarData):
        dt = datetime.datetime.strptime(bar.date, "%Y%m%d %H:%M:%S")
        d = dt.date()

        if self.cur_date != d:
            if self.cur_file:
                self.cur_file.close()
            self.cur_date = d
            filename = "{date}_{ticker}.csv".format(date=d, ticker=self.ticker)
            filepath = os.path.join(self.base_dir, filename)
            os.makedirs(self.base_dir, exist_ok=True)
            self.cur_file = open(filepath, "w")
            self.cur_file.write(",".join(self.BAR_COLUMNS) + "\n")

        fields = [str(getattr(bar, f)) for f in self.BAR_COLUMNS]
        self.cur_file.write(",".join(fields) + "\n")

    def finalize(self):
        self.cur_date = None
        if self.cur_file:
            self.cur_file.close()
            self.cur_file = None


class SnapshotDriver():
    REQ_HISTORICAL = 1

    class Request:
        def __init__(self, contract: Contract, endtime: datetime.datetime,
                     duration="3 M", barsize="5 mins", after_hours=False):
            self.contract = contract
            self.endtime = endtime
            self.duration = duration
            self.barsize = barsize
            self.after_hours = after_hours

    @staticmethod
    def create_machine(model):
        states = [
            "initial",
            "req_historical",
            "finalize",
        ]
        after_state = lambda s: states[states.index(s)+1:]
        # set up state machine
        machine = Machine(model=model, initial="initial", states=states)
        machine.add_transition("error", "*", "finalize",
                               conditions=["is_fatal_error"],
                               before=["log_error"],
                               after=["disconnect"])
        machine.add_transition("error", "*", "=", before="log_error")
        machine.add_transition("stop", "*", "finalize", after="disconnect")
        machine.add_transition("nextValidId", "initial", "req_historical",
                               after="send_req_historical")
        machine.add_transition("historicalData", "req_historical", "=",
                               after="save_bar_data")
        machine.add_transition("historicalDataEnd",
                               "req_historical",
                               "=",
                               conditions=["is_request_pending"],
                               after="send_req_historical")
        machine.add_transition("historicalDataEnd",
                               "req_historical",
                               "finalize",
                               unless=["is_request_pending"],
                               after=["cleanup", "disconnect"])

    def __init__(self, app: EClient, requests : list):
        self.app = app
        self.requests = requests
        self.row_index = 0
        self.current_writer = None

        # configuration options
        self.machine = SnapshotDriver.create_machine(self)

    def log_error(self, req_id, error_code, error_str, **__):
        """ Logs a received error """
        logger.error(f"{error_str} (req_id:{req_id}, error_code:{error_code})")

    def disconnect(self, *_, **__):
        """ Requests the client to disconnect """
        self.app.disconnect()

    #--- Conditions ---
    def is_fatal_error(self, _, error_code, __, **___):
        """ True if the error is fatal and system should stop, else False """
        if error_code >= 2000 and error_code < 10000:
            return False
        elif error_code == 10167: # delayed market data instead
            return False
        else:
            return True

    def is_request_pending(self, *_):
        return len(self.requests) > 0

    def send_req_historical(self, *_, **__):
        request = self.requests.pop()
        local_symbol = request.contract.localSymbol
        if self.current_writer:
            self.current_writer.finalize()
        self.current_writer = SnapshotWriter(local_symbol)

        query_time = request.endtime.strftime("%Y%m%d %H:%M:%S")
        self.app.reqHistoricalData(self.REQ_HISTORICAL,
                                   request.contract,
                                   query_time,
                                   request.duration,
                                   request.barsize,
                                   "TRADES",
                                   0 if request.after_hours else 1,
                                   1,
                                   False, # keep up to date
                                   [])

    def save_bar_data(self, req_id: int, bar: BarData):
        self.current_writer.save_bar(bar)

    def cleanup(self, *args):
        if self.current_writer:
            self.current_writer.finalize()

class SnapshotWrapper(EWrapper):

    def __init__(self, driver : SnapshotDriver):
        EWrapper.__init__(self)
        self.driver = driver

    def __getattribute__(self, item):
        driver = super(SnapshotWrapper, self).__getattribute__("driver")
        try:
            return getattr(driver, item)
        except AttributeError:
            return super(SnapshotWrapper, self).__getattribute__(item)


class SnapshotApp(EClient):
    EQUITY_MAPPER = [("H", 3), ("M", 6), ("U", 9), ("Z", 12), ("H", 3)]

    MAPPERS = {
        "ES": EQUITY_MAPPER,
        "NQ": EQUITY_MAPPER,
        "RTY": EQUITY_MAPPER,
        "YM": EQUITY_MAPPER,
    }

    @staticmethod
    def third_friday(year, month):
        fridays = [d for d in range(1, 22) if
                   datetime.datetime(year=year, month=month,
                                     day=d).weekday() == 4]
        return datetime.datetime(year=year, month=month, day=fridays[2])

    @staticmethod
    def get_roll_dates(year : int, mapper=EQUITY_MAPPER):
        expiration_years = [year] * 4 + [year + 1]
        roll_dates = OrderedDict([(SnapshotApp.third_friday(y, m[1])
                                   - datetime.timedelta(days=8),
                                   m[0])
                                  for y, m in zip(expiration_years, mapper)])
        return roll_dates

    @staticmethod
    def futures_contract(ticker: str, exchange: str):
        # ! [futcontract_local_symbol]
        contract = Contract()
        contract.secType = "FUT"
        contract.exchange = exchange
        contract.currency = "USD"
        contract.localSymbol = ticker
        # ! [futcontract_local_symbol]
        return contract

    @staticmethod
    def compute_ticker(base: str, exchange: str, mapper: list,
                       end_date: datetime.datetime):
        """ third Friday in the third month of each quarter """
        roll_dates = SnapshotApp.get_roll_dates(end_date.year, mapper=mapper)
        expiration_label = next(roll_dates[dt] for dt in roll_dates
                                if dt > end_date)
        year_suffix = str(end_date.year)[-1:]
        ticker = f"{base}{expiration_label}{year_suffix}"
        return SnapshotApp.futures_contract(ticker, exchange)

    def __init__(self, base="ES", exchange="GLOBEX"):
        mapper = self.MAPPERS[base]
        end_date = datetime.datetime.today()
        contract = SnapshotApp.compute_ticker(base, exchange, mapper,
                                              end_date=end_date)
        self.requests = [SnapshotDriver.Request(contract, end_date)]
        self.driver = SnapshotDriver(self, self.requests)
        wrapper = SnapshotWrapper(self.driver)
        EClient.__init__(self, wrapper=wrapper)

    def keyboardInterrupt(self):
        self.driver.stop()

def configure_parser(parser):
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=7497, type=int)
    parser.add_argument("--clientid", default=0, type=int)
    parser.add_argument("--symbol", default="ES")
    parser.add_argument("--exchange", default="GLOBEX")
    return parser

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="""
    Gets an Option Chain snapshot
    """)

    parser.add_argument("-v", "--verbose", action="store_true")

    configure_parser(parser)

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)

    app = SnapshotApp(base=args.symbol, exchange=args.exchange)
    app.connect(args.host, args.port, args.clientid)
    app.run()