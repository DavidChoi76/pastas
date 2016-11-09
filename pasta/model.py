from collections import OrderedDict

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from checks import check_oseries
from solver import LmfitSolve
from tseries import Constant


class Model:
    def __init__(self, oseries, xy=(0, 0), metadata=None, freq=None,
                 fillnan='drop'):
        """
        Initiates a time series model.

        Parameters
        ----------
        oseries: pd.Series
            pandas Series object containing the dependent time series. The
            observation can be non-equidistant.
        xy: Optional[tuple]
            XY location of the oseries in lat-lon format.
        metadata: Optional[dict]
            Dictionary containing metadata of the model.
        freq: Optional[str]
            String containing the desired frequency. By default freq=None and the
            observations are used as they are. The required string format is found
            at http://pandas.pydata.org/pandas-docs/stable/timeseries.html#offset
            -aliases
        fillnan: Optional[str or float]
            Methods or float number to fill nan-values. Default values is
            'drop'. Currently supported options are: 'interpolate', float,
            'mean' and, 'drop'. Interpolation is performed with a standard linear
            interpolation.

        """
        self.oseries = check_oseries(oseries, freq, fillnan)
        self.xy = xy
        self.metadata = metadata
        self.odelt = self.oseries.index.to_series().diff() / np.timedelta64(1, 'D')
        # delt converted to days
        self.tseriesdict = OrderedDict()
        self.noisemodel = None
        self.noiseparameters = None
        self.tmin = None
        self.tmax = None

    def add_tseries(self, tseries):
        """
        adds a time series model component to the Model.

        """
        self.tseriesdict[tseries.name] = tseries

    def add_noisemodel(self, noisemodel):
        """
        Adds a noise model to the time series Model.

        """
        self.noisemodel = noisemodel

    def simulate(self, parameters=None, tmin=None, tmax=None, freq='D'):
        """

        Parameters
        ----------
        t: Optional[pd.series.index]
            Time indices to use for the simulation of the time series model.
        p: Optional[array]
            Array of the parameters used in the time series model.
        noise:

        Returns
        -------
        Pandas Series object containing the simulated time series.

        """

        # Default option when not tmin and tmax is provided
        if tmin is None:
            tmin = self.tmin
        if tmax is None:
            tmax = self.tmax
        assert (tmin is not None) and (
            tmax is not None), 'model needs to be solved first'

        tindex = pd.date_range(tmin, tmax, freq=freq)

        if parameters is None:
            parameters = self.parameters.optimal.values
        h = pd.Series(data=0, index=tindex)
        istart = 0  # Track parameters index to pass to ts object
        for ts in self.tseriesdict.values():
            h += ts.simulate(parameters[istart: istart + ts.nparam], tindex)
            istart += ts.nparam
        return h

    def residuals(self, parameters=None, tmin=None, tmax=None, noise=True):
        """
        Method to calculate the residuals.

        """
        if tmin is None:
            tmin = self.oseries.index.min()
        if tmax is None:
            tmax = self.oseries.index.max()
        tindex = self.oseries[tmin: tmax].index  # times used for calibration

        if parameters is None:
            parameters = self.parameters.optimal.values

        # h_observed - h_simulated
        r = self.oseries[tindex] - self.simulate(parameters, tmin, tmax)[tindex]
        # print 'step1:', sum(r**2)
        if noise and (self.noisemodel is not None):
            r = self.noisemodel.simulate(r, self.odelt[tindex],
                                         parameters[-self.noisemodel.nparam:],
                                         tindex)
        # print 'step2:', sum(r**2)
        if np.isnan(sum(r ** 2)):
            print 'nan problem in residuals'  # quick and dirty check
        return r

    def sse(self, parameters=None, tmin=None, tmax=None, noise=True):
        res = self.residuals(parameters, tmin=tmin, tmax=tmax, noise=noise)
        return sum(res ** 2)

    def initialize(self, initial=True, noise=True):
        if not initial:
            optimal = self.parameters.optimal
        self.nparam = sum(ts.nparam for ts in self.tseriesdict.values())
        if self.noisemodel is not None:
            self.nparam += self.noisemodel.nparam
        self.parameters = pd.DataFrame(columns=['initial', 'pmin', 'pmax',
                                                'vary', 'optimal', 'name'])
        for ts in self.tseriesdict.values():
            self.parameters = self.parameters.append(ts.parameters)
        if self.noisemodel and noise:
            self.parameters = self.parameters.append(self.noisemodel.parameters)
        if not initial:
            self.parameters.initial = optimal

    def solve(self, tmin=None, tmax=None, solver=LmfitSolve, report=True,
              noise=True, initial=True, solve=True):
        """
        Methods to solve the time series model.

        Parameters
        ----------
        tmin: Optional[str]
            String with a start date for the simulation period (E.g. '1980')
        tmax: Optional[str]
            String with an end date for the simulation period (E.g. '2010')
        solver: Optional[solver class]
            Class used to solve the model. Default is lmfit (LmfitSolve)
        report: Boolean
            Print a report to the screen after optimization finished.
        noise: Boolean
            Use the nose model (True) or not (False).
        initialize: Boolean
            Reset initial parameteres.

        """
        if noise and (self.noisemodel is None):
            print 'Warning, solution with noise model while noise model is not ' \
                  'defined. No noise model is used'

        # Check series with tmin, tmax
        self.set_tmin_tmax(tmin, tmax)

        # Initialize parameters
        self.initialize(initial=initial, noise=noise)

        # Solve model
        fit = solver(self, tmin=self.tmin, tmax=self.tmax, noise=noise)

        self.parameters.optimal = fit.optimal_params
        self.report = fit.report
        if report: print self.report

        # self.stats = Statistics(self)

    def set_tmin_tmax(self, tmin=None, tmax=None):
        """
        Function to check if the dependent and independent time series match.

        - tmin and tmax are in oseries.index for optimization.
        - at least one stress is available for simulation between tmin and tmax.
        -

        Parameters
        ----------
        tmin
        tmax

        Returns
        -------

        """

        # Store tmax and tmin. If none is provided, use oseries to set them.
        if tmin is None:
            tmin = self.oseries.index.min()
        else:
            tmin = pd.tslib.Timestamp(tmin)
            assert (tmin >= self.oseries.index[0]) and (tmin <= self.oseries.index[
                -1]), 'Error: Specified tmin is outside of the oseries'
        if tmax is None:
            tmax = self.oseries.index.max()
        else:
            tmax = pd.tslib.Timestamp(tmax)
            assert (tmax >= self.oseries.index[0]) and (tmax <= self.oseries.index[
                -1]), 'Error: Specified tmin is outside of the oseries'
        assert tmax > tmin, 'Error: Specified tmax not larger than specified tmin'
        assert len(self.oseries[
                   tmin: tmax]) > 0, 'Error: no observations between tmin and tmax'

        self.tmin = tmin
        self.tmax = tmax

        # TODO
        # Check if at least one stress overlaps with the oseries data

    def get_response(self, name):
        try:
            p = self.parameters.loc[self.parameters.name == name, 'optimal'].values
            return self.tseriesdict[name].simulate(p)
        except KeyError:
            print "Name not in tseriesdict, available names are: %s" \
                  % self.tseriesdict.keys()

    def get_response_function(self, name):
        try:
            p = self.parameters.loc[self.parameters.name == name, 'optimal'].values
            return self.tseriesdict[name].rfunc.block(p)
        except KeyError:
            print "Name not in tseriesdict, available names are: %s" \
                  % self.tseriesdict.keys()

    def get_stress(self, name):
        try:
            p = self.parameters.loc[self.parameters.name == name, 'optimal'].values
            return self.tseriesdict[name].get_stress(p)
        except KeyError:
            print "Name not in tseriesdict, available names are: %s" \
                  % self.tseriesdict.keys()

    def plot(self, tmin=None, tmax=None, oseries=True, simulate=True):
        """

        Parameters
        ----------
        oseries: Boolean
            True to plot the observed time series.

        Returns
        -------
        Plot of the simulated and optionally the observed time series

        """
        plt.figure()
        if simulate:
            h = self.simulate(tmin=tmin, tmax=tmax)
            h.plot()
        if oseries:
            self.oseries.plot(linestyle='', marker='.', color='k', markersize=3)
        plt.show()

    def plot_results(self, tmin=None, tmax=None, savefig=False):
        """

        Parameters
        ----------
        tmin/tmax: str
            start and end time for plotting
        savefig: Optional[Boolean]
            True to save the figure, False is default. Figure is saved in the
            current working directory when running your python scripts.

        Returns
        -------

        """
        plt.figure('Model Results', facecolor='white')
        gs = plt.GridSpec(3, 4, wspace=0.2)

        # Plot the Groundwater levels
        h = self.simulate(tmin=tmin, tmax=tmax)
        ax1 = plt.subplot(gs[:2, :-1])
        h.plot(label='modeled head')
        self.oseries.plot(linestyle='', marker='.', color='k', markersize=3,
                          label='observed head')
        # ax1.xaxis.set_visible(False)
        plt.legend(loc=(0, 1), ncol=3, frameon=False, handlelength=3)
        plt.ylabel('Head [m]')

        # Plot the residuals and innovations
        residuals = self.residuals(tmin=tmin, tmax=tmax)
        ax2 = plt.subplot(gs[2, :-1])  # , sharex=ax1)
        residuals.plot(color='k', label='residuals')
        # Ruben Calje commented next three lines on 31-10-2016:
        #if self.noisemodel is not None:
            #innovations = self.noisemodel.simulate(residuals, self.odelt)
            #innovations.plot(label='innovations')
        plt.legend(loc=(0, 1), ncol=3, frameon=False, handlelength=3)
        plt.ylabel('Error [m]')
        plt.xlabel('Time [Years]')

        # Plot the Impulse Response Function
        ax3 = plt.subplot(gs[0, -1])
        n = 0
        for ts in self.tseriesdict.values():
            p = self.parameters[n:n + ts.nparam]
            n += ts.nparam
            if "rfunc" in dir(ts):
                plt.plot(ts.rfunc.block(p.optimal))
        ax3.set_xticks(ax3.get_xticks()[::2])
        ax3.set_yticks(ax3.get_yticks()[::2])
        plt.title('Block Response')

        # Plot the Model Parameters (Experimental)
        ax4 = plt.subplot(gs[1:2, -1])
        ax4.xaxis.set_visible(False)
        ax4.yaxis.set_visible(False)
        text = np.vstack((self.parameters.keys(), [round(float(i), 4) for i in
                                                  self.parameters.optimal.values])).T
        colLabels = ("Parameter", "Value")
        ytable = ax4.table(cellText=text, colLabels=colLabels, loc='center')
        ytable.scale(1, 1.1)

        # Table of the numerical diagnostic statistics.
        ax5 = plt.subplot(gs[2, -1])
        ax5.xaxis.set_visible(False)
        ax5.yaxis.set_visible(False)
        # Ruben Calje commented next two lines on 31-10-2016:
        #plt.text(0.05, 0.8, 'AIC: %.2f' % self.fit.aic)
        #plt.text(0.05, 0.6, 'BIC: %.2f' % self.fit.bic)
        plt.show()
        if savefig:
            plt.savefig('.eps' % (self.name), bbox_inches='tight')

    def plot_decomposition(self, tmin=None, tmax=None, freq='D'):
        # Default option when not tmin and tmax is provided
        if tmin is None:
            tmin = self.tmin
        if tmax is None:
            tmax = self.tmax
        assert (tmin is not None) and (
            tmax is not None), 'model needs to be solved first'

        tindex = pd.date_range(tmin, tmax, freq=freq)

        ts = self.tseriesdict
        n = len(ts)
        f, axarr = plt.subplots(1 + n, sharex=True)

        # plot combination in top-graph
        axarr[0].set_title('Observations and simulation')

        h = self.simulate(tmin=tmin, tmax=tmax)
        h.plot(ax=axarr[0], label='simulation')
        self.oseries.plot(linestyle='', marker='.', color='k', markersize=3, ax=axarr[0], label='observations')
        handles, labels = axarr[0].get_legend_handles_labels()
        leg=axarr[0].legend(handles, labels, loc=2)
        leg.get_frame().set_alpha(0.5)

        parameters = self.parameters.optimal.values
        istart = 0  # Track parameters index to pass to ts object
        iax = 1
        for ts in self.tseriesdict.values():
            h = ts.simulate(parameters[istart: istart + ts.nparam], tindex)
            axarr[iax].set_title(ts.name)
            if isinstance(ts, Constant):
                xlim = axarr[iax].get_xlim()
                axarr[iax].plot(xlim,[h,h])
            else:
                h.plot(ax=axarr[iax])
            istart += ts.nparam
            iax += 1
        # show the figure
        plt.show()