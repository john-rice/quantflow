

class TradingAlgorithm(object):
    """
    Base class for trading algorithms. Inherit and overload
    initialize() and handle_data(data).

    A new algorithm could look like this:
    ```
    class MyAlgo(TradingAlgorithm):
        def initialize(self, sids, amount):
            self.sids = sids
            self.amount = amount

        def handle_data(self, data):
            sid = self.sids[0]
            amount = self.amount
            self.order(sid, amount)
    ```
    To then to run this algorithm:

    my_algo = MyAlgo([0], 100) # first argument has to be list of sids
    stats = my_algo.run(data)

    """
    def __init__(self, *args, **kwargs):
        """Initialize sids and other state variables.

        :Arguments:
            data_frequency : str (daily, hourly or minutely)
               The duration of the bars.
            annualizer : int <optional>
               Which constant to use for annualizing risk metrics.
               If not provided, will extract from data_frequency.
            capital_base : float <default: 1.0e5>
               How much capital to start with.
            instant_fill : bool <default: False>
               Whether to fill orders immediately or on next bar.
        """
        self.datetime = None

        self.registered_transforms = {}
        self.transforms = []
        self.sources = []

        self._recorded_vars = {}

        self.logger = None

        self.benchmark_return_source = None
        self.perf_tracker = None

        # default components for transact
        self.slippage = VolumeShareSlippage()
        self.commission = PerShare()

        if 'data_frequency' in kwargs:
            self.set_data_frequency(kwargs.pop('data_frequency'))
        else:
            self.data_frequency = None

        self.instant_fill = kwargs.pop('instant_fill', False)

        # Override annualizer if set
        if 'annualizer' in kwargs:
            self.annualizer = kwargs['annualizer']

        # set the capital base
        self.capital_base = kwargs.pop('capital_base', DEFAULT_CAPITAL_BASE)

        self.sim_params = kwargs.pop('sim_params', None)
        if self.sim_params:
            self.sim_params.data_frequency = self.data_frequency
            self.perf_tracker = PerformanceTracker(self.sim_params)

        self.blotter = kwargs.pop('blotter', None)
        if not self.blotter:
            self.blotter = Blotter()

        self.portfolio_needs_update = True
        self._portfolio = None

        # an algorithm subclass needs to set initialized to True when
        # it is fully initialized.
        self.initialized = False

        # call to user-defined constructor method
        self.initialize(*args, **kwargs)

    def _create_data_generator(self, source_filter, sim_params):
        """
        Create a merged data generator using the sources and
        transforms attached to this algorithm.

        ::source_filter:: is a method that receives events in date
        sorted order, and returns True for those events that should be
        processed by the zipline, and False for those that should be
        skipped.
        """
        if self.benchmark_return_source is None:
            benchmark_return_source = [
                Event({'dt': dt,
                       'returns': ret,
                       'type': zipline.protocol.DATASOURCE_TYPE.BENCHMARK,
                       'source_id': 'benchmarks'})
                for dt, ret in trading.environment.benchmark_returns.iterkv()
                if dt.date() >= sim_params.period_start.date()
                and dt.date() <= sim_params.period_end.date()
            ]
        else:
            benchmark_return_source = self.benchmark_return_source

        date_sorted = date_sorted_sources(*self.sources)

        if source_filter:
            date_sorted = filter(source_filter, date_sorted)

        with_tnfms = sequential_transforms(date_sorted,
                                           *self.transforms)
        with_alias_dt = alias_dt(with_tnfms)

        with_benchmarks = date_sorted_sources(benchmark_return_source,
                                              with_alias_dt)

        # Group together events with the same dt field. This depends on the
        # events already being sorted.
        return groupby(with_benchmarks, attrgetter('dt'))

    def _create_generator(self, sim_params, source_filter=None):
        """
        Create a basic generator setup using the sources and
        transforms attached to this algorithm.

        ::source_filter:: is a method that receives events in date
        sorted order, and returns True for those events that should be
        processed by the zipline, and False for those that should be
        skipped.
        """
        sim_params.data_frequency = self.data_frequency

        # perf_tracker will be instantiated in __init__ if a sim_params
        # is passed to the constructor. If not, we instantiate here.
        if self.perf_tracker is None:
            self.perf_tracker = PerformanceTracker(sim_params)

        self.data_gen = self._create_data_generator(source_filter,
                                                    sim_params)

        self.trading_client = AlgorithmSimulator(self, sim_params)

        transact_method = transact_partial(self.slippage, self.commission)
        self.set_transact(transact_method)

        return self.trading_client.transform(self.data_gen)

    def get_generator(self):
        """
        Override this method to add new logic to the construction
        of the generator. Overrides can use the _create_generator
        method to get a standard construction generator.
        """
        return self._create_generator(self.sim_params)

    def initialize(self, *args, **kwargs):
        pass

    # TODO: make a new subclass, e.g. BatchAlgorithm, and move
    # the run method to the subclass, and refactor to put the
    # generator creation logic into get_generator.
    def run(self, source, sim_params=None, benchmark_return_source=None):
        """Run the algorithm.

        :Arguments:
            source : can be either:
                     - pandas.DataFrame
                     - zipline source
                     - list of zipline sources

               If pandas.DataFrame is provided, it must have the
               following structure:
               * column names must consist of ints representing the
                 different sids
               * index must be DatetimeIndex
               * array contents should be price info.

        :Returns:
            daily_stats : pandas.DataFrame
              Daily performance metrics such as returns, alpha etc.

        """
        if isinstance(source, (list, tuple)):
            assert self.sim_params is not None or sim_params is not None, \
                """When providing a list of sources, \
                sim_params have to be specified as a parameter
                or in the constructor."""
        elif isinstance(source, pd.DataFrame):
            # if DataFrame provided, wrap in DataFrameSource
            source = DataFrameSource(source)
        elif isinstance(source, pd.Panel):
            source = DataPanelSource(source)

        if not isinstance(source, (list, tuple)):
            self.sources = [source]
        else:
            self.sources = source

        # Check for override of sim_params.
        # If it isn't passed to this function,
        # use the default params set with the algorithm.
        # Else, we create simulation parameters using the start and end of the
        # source provided.
        if not sim_params:
            if not self.sim_params:
                start = source.start
                end = source.end

                sim_params = create_simulation_parameters(
                    start=start,
                    end=end,
                    capital_base=self.capital_base
                )
            else:
                sim_params = self.sim_params

        # Create transforms by wrapping them into StatefulTransforms
        self.transforms = []
        for namestring, trans_descr in iteritems(self.registered_transforms):
            sf = StatefulTransform(
                trans_descr['class'],
                *trans_descr['args'],
                **trans_descr['kwargs']
            )
            sf.namestring = namestring

            self.transforms.append(sf)

        # force a reset of the performance tracker, in case
        # this is a repeat run of the algorithm.
        self.perf_tracker = None

        # create transforms and zipline
        self.gen = self._create_generator(sim_params)

        # loop through simulated_trading, each iteration returns a
        # perf dictionary
        perfs = []
        for perf in self.gen:
            perfs.append(perf)

        # convert perf dict to pandas dataframe
        daily_stats = self._create_daily_stats(perfs)

        return daily_stats

    def _create_daily_stats(self, perfs):
        # create daily and cumulative stats dataframe
        daily_perfs = []
        # TODO: the loop here could overwrite expected properties
        # of daily_perf. Could potentially raise or log a
        # warning.
        for perf in perfs:
            if 'daily_perf' in perf:

                perf['daily_perf'].update(
                    perf['daily_perf'].pop('recorded_vars')
                )
                daily_perfs.append(perf['daily_perf'])
            else:
                self.risk_report = perf

        daily_dts = [np.datetime64(perf['period_close'], utc=True)
                     for perf in daily_perfs]
        daily_stats = pd.DataFrame(daily_perfs, index=daily_dts)

        return daily_stats

    def add_transform(self, transform_class, tag, *args, **kwargs):
        """Add a single-sid, sequential transform to the model.

        :Arguments:
            transform_class : class
                Which transform to use. E.g. mavg.
            tag : str
                How to name the transform. Can later be access via:
                data[sid].tag()

        Extra args and kwargs will be forwarded to the transform
        instantiation.

        """
        self.registered_transforms[tag] = {'class': transform_class,
                                           'args': args,
                                           'kwargs': kwargs}

    def record(self, **kwargs):
        """
        Track and record local variable (i.e. attributes) each day.
        """
        for name, value in kwargs.items():
            self._recorded_vars[name] = value

    def order(self, sid, amount, limit_price=None, stop_price=None):
        return self.blotter.order(sid, amount, limit_price, stop_price)

    def order_value(self, sid, value, limit_price=None, stop_price=None):
        """
        Place an order by desired value rather than desired number of shares.
        If the requested sid is found in the universe, the requested value is
        divided by its price to imply the number of shares to transact.

        value > 0 :: Buy/Cover
        value < 0 :: Sell/Short
        Market order:    order(sid, value)
        Limit order:     order(sid, value, limit_price)
        Stop order:      order(sid, value, None, stop_price)
        StopLimit order: order(sid, value, limit_price, stop_price)
        """
        last_price = self.trading_client.current_data[sid].price
        if np.allclose(last_price, 0):
            zero_message = "Price of 0 for {psid}; can't infer value".format(
                psid=sid
            )
            self.logger.debug(zero_message)
            # Don't place any order
            return
        else:
            amount = value / last_price
            return self.order(sid, amount, limit_price, stop_price)

    @property
    def recorded_vars(self):
        return copy(self._recorded_vars)

    @property
    def portfolio(self):
        # internally this will cause a refresh of the
        # period performance calculations.
        return self.perf_tracker.get_portfolio()

    def updated_portfolio(self):
        # internally this will cause a refresh of the
        # period performance calculations.
        if self.portfolio_needs_update:
            self._portfolio = self.perf_tracker.get_portfolio()
            self.portfolio_needs_update = False
        return self._portfolio

    def set_logger(self, logger):
        self.logger = logger

    def set_datetime(self, dt):
        assert isinstance(dt, datetime), \
            "Attempt to set algorithm's current time with non-datetime"
        assert dt.tzinfo == pytz.utc, \
            "Algorithm expects a utc datetime"
        self.datetime = dt

    def get_datetime(self):
        """
        Returns a copy of the datetime.
        """
        date_copy = copy(self.datetime)
        assert date_copy.tzinfo == pytz.utc, \
            "Algorithm should have a utc datetime"
        return date_copy

    def set_transact(self, transact):
        """
        Set the method that will be called to create a
        transaction from open orders and trade events.
        """
        self.blotter.transact = transact

    def set_slippage(self, slippage):
        if not isinstance(slippage, SlippageModel):
            raise UnsupportedSlippageModel()
        if self.initialized:
            raise OverrideSlippagePostInit()
        self.slippage = slippage

    def set_commission(self, commission):
        if not isinstance(commission, (PerShare, PerTrade, PerDollar)):
            raise UnsupportedCommissionModel()

        if self.initialized:
            raise OverrideCommissionPostInit()
        self.commission = commission

    def set_sources(self, sources):
        assert isinstance(sources, list)
        self.sources = sources

    def set_transforms(self, transforms):
        assert isinstance(transforms, list)
        self.transforms = transforms

    def set_data_frequency(self, data_frequency):
        assert data_frequency in ('daily', 'minute')
        self.data_frequency = data_frequency
        self.annualizer = ANNUALIZER[self.data_frequency]

    def order_percent(self, sid, percent, limit_price=None, stop_price=None):
        """
        Place an order in the specified security corresponding to the given
        percent of the current portfolio value.

        Note that percent must expressed as a decimal (0.50 means 50\%).
        """
        value = self.portfolio.portfolio_value * percent
        return self.order_value(sid, value, limit_price, stop_price)

    def order_target(self, sid, target, limit_price=None, stop_price=None):
        """
        Place an order to adjust a position to a target number of shares. If
        the position doesn't already exist, this is equivalent to placing a new
        order. If the position does exist, this is equivalent to placing an
        order for the difference between the target number of shares and the
        current number of shares.
        """
        if sid in self.portfolio.positions:
            current_position = self.portfolio.positions[sid].amount
            req_shares = target - current_position
            return self.order(sid, req_shares, limit_price, stop_price)
        else:
            return self.order(sid, target, limit_price, stop_price)

    def order_target_value(self, sid, target, limit_price=None,
                           stop_price=None):
        """
        Place an order to adjust a position to a target value. If
        the position doesn't already exist, this is equivalent to placing a new
        order. If the position does exist, this is equivalent to placing an
        order for the difference between the target value and the
        current value.
        """
        if sid in self.portfolio.positions:
            current_position = self.portfolio.positions[sid].amount
            current_price = self.portfolio.positions[sid].last_sale_price
            current_value = current_position * current_price
            req_value = target - current_value
            return self.order_value(sid, req_value, limit_price, stop_price)
        else:
            return self.order_value(sid, target, limit_price, stop_price)

    def order_target_percent(self, sid, target, limit_price=None,
                             stop_price=None):
        """
        Place an order to adjust a position to a target percent of the
        current portfolio value. If the position doesn't already exist, this is
        equivalent to placing a new order. If the position does exist, this is
        equivalent to placing an order for the difference between the target
        percent and the current percent.

        Note that target must expressed as a decimal (0.50 means 50\%).
        """
        if sid in self.portfolio.positions:
            current_position = self.portfolio.positions[sid].amount
            current_price = self.portfolio.positions[sid].last_sale_price
            current_value = current_position * current_price
        else:
            current_value = 0
        target_value = self.portfolio.portfolio_value * target

        req_value = target_value - current_value
        return self.order_value(sid, req_value, limit_price, stop_price)

    def get_open_orders(self, sid=None):
        if sid is None:
            return {key: [order.to_api_obj() for order in orders]
                    for key, orders
                    in self.blotter.open_orders.iteritems()}
        if sid in self.blotter.open_orders:
            orders = self.blotter.open_orders[sid]
            return [order.to_api_obj() for order in orders]
        return []

    def get_order(self, order_id):
        if order_id in self.blotter.orders:
            return self.blotter.orders[order_id].to_api_obj()

    def cancel_order(self, order_param):
        order_id = order_param
        if isinstance(order_param, zipline.protocol.Order):
            order_id = order_param.id

        self.blotter.cancel(order_id)

    def raw_positions(self):
        """
        Returns the current portfolio for the algorithm.

        N.B. this is not done as a property, so that the function can be
        passed and called from within a source.
        """
        # Return the 'internal' positions object, as in the one that is
        # not passed to the algo, and thus should not have tainted keys.
        return self.perf_tracker.cumulative_performance.positions

    def raw_orders(self):
        """
        Returns the current open orders from the blotter.

        N.B. this is not a property, so that the function can be passed
        and called back from within a source.
        """

        return self.blotter.open_orders
