import logging
import datetime

import pandas as pd
from transitions import Machine

from ibapi.common import BarData
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.ticktype import TickType, TickTypeEnum

logger = logging.getLogger(__name__)


class SnapshotDriver():
    REQ_HISTORICAL = 1

    BAR_COLUMNS = [
        "date", "open", "high", "low", "close", "volume", "barCount", "average",
    ]

    @staticmethod
    def third_friday(year, month):
        fridays = [d for d in range(1, 22) if
                   datetime.datetime(year=year, month=month,
                                     day=d).weekday() == 4]
        return datetime.datetime(year=year, month=month, day=fridays[2])

    @staticmethod
    def compute_ticker(base="ES", end_date=datetime.datetime.today()):
        """ third Friday in the third month of each quarter """
        expiration_labels = ["H", "M", "U", "Z", "H"]
        expiration_months = [3, 6, 9, 12, 3]
        expiration_years = [end_date.year] * 4 + [end_date.year + 1]
        expiration_dates = [SnapshotDriver.third_friday(y, m)
                            for y, m in zip(expiration_years,
                                            expiration_months)]
        expiration_label = expiration_labels[
            next(i for i in range(5) if expiration_dates[i] > end_date)]
        year_suffix = str(end_date.year)[-1:]
        return f"{base}{expiration_label}{year_suffix}"

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
                               "finalize",
                               after="disconnect")

    def __init__(self, app : EClient, **kwargs):
        self.app = app
        self.base_symbol = kwargs.get("base_symbol")
        self.exchange = kwargs.get("exchange")
        self.results = pd.DataFrame(columns=self.BAR_COLUMNS)
        self.endtime_index = datetime.datetime.today()
        self.row_index = 0

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
            if self.market_data_type == self.MARKET_DATA_REALTIME:
                return True
            else:
                return False
        else:
            return True

    def send_req_historical(self, event):
        local_symbol = self.compute_ticker(self.base_symbol, self.endtime_index)
        contract = self.futures_contract(local_symbol, self.exchange)
        query_time = self.endtime_index.strftime("%Y%m%d %H:%M:%S")
        self.app.reqHistoricalData(self.REQ_HISTORICAL,
                                   contract, query_time,
                                   "1 D", "1 min", "TRADES",
                                   1, # useRTH - set to 0 to get after hours
                                   1,
                                   False, # keep up to date
                                   [])

    def save_bar_data(self, reqId:int, bar: BarData):
        self.results.loc[self.row_index] = [
            getattr(bar, column) for column in self.results.columns]
        self.row_index += 1


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
    def __init__(self, base_symbol : str, exchange : str):
        self.driver = SnapshotDriver(self,
                                     base_symbol=base_symbol,
                                     exchange=exchange)
        wrapper = SnapshotWrapper(self.driver)
        EClient.__init__(self, wrapper=wrapper)

    def keyboardInterrupt(self):
        self.driver.stop()

    def get_result(self):
        return self.driver.results

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

    app = SnapshotApp(args.symbol, args.exchange)
    app.connect(args.host, args.port, args.clientid)
    app.run()

    result = app.get_result()
    print(result)
    result.to_csv("{}.csv".format(args.symbol))