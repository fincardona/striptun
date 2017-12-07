#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

'''Compute the bandwidth and the central frequency of the polarimeter'''

from json_save import save_parameters_to_json
from argparse import ArgumentParser
from scipy import signal
from reports import create_report, get_code_version_params
from file_access import load_timestream
import logging as log
import numpy as np
import matplotlib.pyplot as plt
import os

SAMPLING_FREQUENCY_HZ = 25.0  # Hz
NAMING_CONVENTION = ['PW0/Q1', 'PW1/U1', 'PW2/U2', 'PW3/Q2']


def get_frequency_range_and_data(nu, data, std_dev=True, rej=1):
    """
    This function does the following:
    - rejects data outside the frequency range imposed by the RF generator. The
    acquisition system returns -1 if there are not frequency data associated to the power data.
    Otherwise, it returns the frequency value.
    - returns the average value of the power for each frequency provided by the RF generator with the associated standard
    deviation.
    -calculate the electronic offset as a straight line from the first to the last point acquired with the RF generator on.
     In this way we take into account possible drifts in time of the electronics.

    Parameters
    ----------
    nu      : numpy array of shape (time*sampling_rate, ),
              The frequency data.
    data    : numpy array of shape (time*sampling_rate, 4),
              The power data.
    std_dev : boolean,
              If True (default) it will return also the standard deviation of the averaged data.
    rej     : integer,
              The number of samples rejected because of frequency uncertainty.

    Returns
    -------
    out : 3 (or 2, if std_dev is False) numpy arrays of shape (number of frequency steps, 4),
          numpy array of shape (4,)
    """
    new_nu_, new_data_ = nu[nu > 0], data[nu > 0]
    new_nu, idx, count = np.unique(
        new_nu_, return_index=True, return_counts=True)
    new_data = np.zeros((len(new_nu), data.shape[-1]))
    new_std_dev = np.zeros((len(new_nu), data.shape[-1]))
    for (i, j), c in zip(enumerate(idx), count):
        new_data[i] = np.median(new_data_[j + rej: j + c - rej], axis=0)
        new_std_dev[i] = np.std(
            new_data_[j + rej: j + c - rej], axis=0) / np.sqrt(c)
    if std_dev:
        return new_nu, new_data, new_std_dev
    return new_nu, new_data


def remove_offset(nu, data):
    """
    This function removes the offset from data.

    Parameters
    ----------def remove_offset(data, offset):

    This function removes the offset from data.

    Parameters
    ----------
    data  : numpy array of shape (time*sampling_rate, 4),
            It is the output power of the 4 detectors.
    offset: numpy array of shape (1,4)
            It is the offset that will be subctrated from data"""

    # offset_low = np.mean(data[(nu >= 38.0) & (nu <= 38.2)], axis=0)
    # offset_high = np.mean(
    # data[(nu >= 49.2) & (nu <= 50.0)], axis=0)
    # offset = np.mean(np.array([offset_low, offset_high]), axis=0)
    # offset = np.amax(data[(nu >= 38.1) & (nu <= 49.9)], axis=0)
    # offset = np.mean(data[new_nu == -1], axis=0)

    """#linear offset (RF generator on)
    offset = np.zeros((len(nu), data.shape[-1]))
    x = [38.0, 50.0]
    for i in range(0, 4):
        y = [data[:, i][nu == 38.0], data[:, i][nu == 50.0]]
        line_coeff = np.polyfit(x, y, 1)
        offset[:, i] = nu * line_coeff[0] + line_coeff[1]"""

    """#offset claudio
    firsthalf_data = data[:int(len(data)/2)]
    firsthalf_nu = nu[:int(len(nu)/2)]
    offset = np.mean(firsthalf_data[firsthalf_nu == -1], axis=0)
    print(offset)
    """
    # linear offset (RF generator off)
    firsthalf_data = data[:int(len(data) / 2)]
    firsthalf_nu = nu[:int(len(nu) / 2)]
    first_offset = np.median(firsthalf_data[firsthalf_nu == -1], axis=0)
    secondhalf_data = data[int(len(data) / 2):]
    secondhalf_nu = nu[int(len(nu) / 2):]
    second_offset = np.median(secondhalf_data[secondhalf_nu == -1], axis=0)

    offset = np.zeros((len(nu), data.shape[-1]))
    x = [np.min(nu[nu > 0]), np.max(nu)]
    for i in range(0, 4):
        y = [first_offset[i], second_offset[i]]
        line_coeff = np.polyfit(x, y, 1)
        offset[:, i] = nu * line_coeff[0] + line_coeff[1]

    data_nooff = data - offset
    return data_nooff


def find_blind_channel(data):
    var_range = np.percentile(data, 95, axis=0) - \
        np.percentile(data, 5, axis=0)
    idx_blind = np.argmin(var_range)

    if(idx_blind == 0):
        pss = '0110'
    if(idx_blind == 3):
        pss = '0101'

    return idx_blind, pss


def get_central_nu_bandwidth(nu, data):
    """This function calculates the bandwidth and the central frequency of the 4 detector bandwidth
    response. Definition are taken according to Bischoff and Newburgh's PhD Theses.

     Parameters
     ----------
     nu    : numpy array of shape (time*sampling_rate, ),
             The frequency data.
     data  : numpy array of shape (time*sampling_rate, 4),
             It is the output power of the 4 detectors.
     Returnsimport matplotlib.lines as llt
     -------
     out : numpy array of shape (4, ), numpy array of shape (4, )
     """
    if np.allclose((nu[1:] - nu[:-1]), (nu[1:] - nu[:-1])[0]) is False:
        raise ValueError('The frequency steps are not uniform! Check out!')
    if data.shape[-1] == len(data):
        data = data[..., None]
    step = (nu[1:] - nu[:-1])[0]
    central_nu = np.sum(data * nu[..., None],
                        axis=0) / np.sum(data, axis=0)
    bandwidth = np.sum(data, axis=0)**2 * step / np.sum(data**2, axis=0)
    if bandwidth.shape[-1] == 1:
        return central_nu[0], bandwidth[0]
    return central_nu, bandwidth


def preliminary_plots(polarimeter_name, freq, data, output_path, pss, file_number, **kwargs):

    def axis_labels():
        plt.ylabel('Detector output' + r'$[ADU]$', fontsize=20)
        plt.xlabel('Frequency [GHz]', fontsize=20)
        plt.xticks(fontsize=16)
        plt.yticks(fontsize=16)

    def save_plot(title, output_path):
        plot_file_path = os.path.join(output_path, plot_name + '.svg')
        plt.savefig(plot_file_path, bbox_inches='tight')
        log.info('Saving plot into file "%s"', plot_file_path)

    def plots(title, freq, data, legend_labels, output_path):
        plt.figure(figsize=(16, 9))
        plt.title(title, fontsize=22)
        plot = plt.plot(freq, data, **kwargs)
        plt.legend(plot, legend_labels, loc='best', fontsize=16)
        plt.grid(axis='y', linewidth=0.5)
        axis_labels()
        save_plot(title, output_path)

    plot_name = polarimeter_name + '_RFtest_' + pss + '_' + str(file_number)
    title = polarimeter_name + ' RFtest - ' + pss + '_' + str(file_number)
    plots(title, freq, data, NAMING_CONVENTION, output_path)


def final_plots(polarimeter_name, freq, norm_data, final_band, final_band_err,  output_path, **kwargs):

    def axis_labels():
        plt.ylabel('Detector output (normalized)', fontsize=20)
        plt.xlabel('Frequency [GHz]', fontsize=20)
        plt.xticks(fontsize=16)
        plt.yticks(fontsize=16)

    def save_plot(title, output_path):
        plot_file_path = os.path.join(output_path, plot_name + '.svg')
        plt.savefig(plot_file_path, bbox_inches='tight')
        log.info('Saving plot into file "%s"', plot_file_path)

    def plots_all(title, freq, norm_data, final_band, legend_labels, output_path):
        plt.figure(figsize=(16, 9))
        plt.title(title, fontsize=22)
        plot = plt.plot(freq, norm_data, ':')
        plt.plot(freq, final_band, color='black')
        plt.legend(plot, legend_labels, loc='best', fontsize=16)
        plt.grid(axis='y', linewidth=0.5)
        axis_labels()
        save_plot(title, output_path)

    def plots_final(title, freq, norm_data, final_band, final_band_err, legend_labels, output_path):
        plt.figure(figsize=(16, 9))
        plt.title(title, fontsize=22)
        plot = plt.plot(freq, final_band, color='black')
        plt.fill_between(freq, final_band - final_band_err, final_band + final_band_err, alpha=0.2,
                         edgecolor='#1B2ACC', facecolor='#089FFF', linewidth=4, linestyle='dashdot', antialiased=True)
        plt.legend(plot, legend_labels, loc='best', fontsize=16)
        plt.grid(axis='y', linewidth=0.5)
        axis_labels()
        save_plot(title, output_path)

    plot_name = polarimeter_name + '_RFtest_AllDetNorm'
    title = polarimeter_name + ' RFtest - All detector outputs (normalized)'
    labels = ['PW0/Q1 0101', 'PW1/U1 0101', 'PW2/U2 0101',
              'PW1/U1 0110', 'PW2/U2 0110', 'PW3/Q2 0110']
    plots_all(title, freq, norm_data, final_band,
              labels, output_path)

    plot_name = polarimeter_name + '_RFtest_FinalBand'
    title = polarimeter_name + ' RFtest - Final Band '
    labels = ['Final band']
    plots_final(title, freq, norm_data, final_band,
                final_band_err, labels, output_path)


def build_dict_from_results(pol_name, duration, PSStatus, central_nu_det, bandwidth_det,
                            final_central_nu, final_central_nu_err,
                            final_bandwidth, final_bandwidth_err):
    results = {
        'polarimeter_name': pol_name,
        'title': 'Bandwidth test for polarimeter {0}'.format(pol_name),
        'sampling_frequency': SAMPLING_FREQUENCY_HZ,
        'test_duration': duration / 60 / 60,
        'final_central_nu': final_central_nu,
        'final_central_nu_err': final_central_nu_err,
        'final_bandwidth': final_bandwidth,
        'final_bandwidth_err': final_bandwidth_err,
    }

    for j, pss in enumerate(PSStatus):
        results['PSStatus' + '_' + str(j)] = pss
        results['ps' + pss + '_' + str(j)] = {}
        for i, nam in enumerate(NAMING_CONVENTION):
            nam = nam.replace("/", "")
            if(pss == '0101' and i == 3 or pss == '0110' and i == 0):
                central_nu_det[j, i] = 0
                bandwidth_det[j, i] = 0
            results['ps' + pss + '_' + str(j)][nam] = {'central_nu': central_nu_det[j, i],
                                                       'bandwidth': bandwidth_det[j, i]}
    return results


def parse_arguments():
    '''Return a class containing the values of the command-line arguments.

    The field accessible from the object returned by this function are the following:

    - ``polarimeter_name``
    - ``input_file_path``
    - ``output_path``
    '''
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('polarimeter_name', type=str,
                        help='''Name of the polarimeter''')
    parser.add_argument('-FILE', action='append', dest='file_list', default=[],
                        help='Add all the files you want to analyze. USAGE: python bandwidth.py -FILE "file1.txt" -FILE "file2.txt" -FILE "file3.txt"')
    parser.add_argument('output_path', type=str,
                        help='''Path to the directory that will contain the
                        report. If the path does not exist, it will be created''')
    return parser.parse_args()


def AnalyzeBandTest(polarimeter_name, file_name, output_path):
    metadata, datafile = load_timestream(file_name)
    nu = datafile[-1]
    data = datafile[-3]

    log.info('File loaded, {0} samples found'.format(len(data[:, 0])))

    duration = len(data) / SAMPLING_FREQUENCY_HZ  # sec

    # Selecting data and removing the electronic offset

    nooffdata = remove_offset(nu, data)
    new_nu, new_data, new_std_dev = get_frequency_range_and_data(
        nu, nooffdata)
    # new_data = remove_offset(new_nu, new_data)

    # Setting to zero non physical values with negative gain
    new_data[new_data > 0] = 0

    # Computing central frequency and equivalent bandwidth for the four detectors
    central_nu_det, bandwidth_det = get_central_nu_bandwidth(
        new_nu, new_data)

    # Computing the average to get central frequency and equivalent bandwidth of the polarimeter (excluding the "blind" detector).
    # phase switch state '0101': PW3 is blind
    # phase switch state '0110': PW0 is blind

    # Finding the "blind" detector
    idx_blind, pss = find_blind_channel(new_data)
    mask = np.ones(4, dtype=bool)
    mask[idx_blind] = False

    central_nu_det = np.ma.masked_array(central_nu_det, mask=~mask)
    bandwidth_det = np.ma.masked_array(bandwidth_det, mask=~mask)

    # Normalizing data to range 0-1
    norm_data = new_data[:, mask] / \
        np.absolute(new_data[:, mask].min(axis=0))

    return duration, pss, new_nu, new_data, norm_data, central_nu_det, bandwidth_det


def main():
    log.basicConfig(format='[%(asctime)s %(levelname)s] %(message)s',
                    level=log.DEBUG)
    args = parse_arguments()

    log.info('Tuning radiometer "%s"', args.polarimeter_name)

    log.info('Writing the report into "%s"', args.output_path)

    # Creating the directory that will contain the report
    os.makedirs(args.output_path, exist_ok=True)

    norm_data_list, central_nu_det, bandwidth_det,  PSStatus = list(), list(), list(), list()

    for i, file_name in enumerate(args.file_list):

        # Loading file
        log.info('Loading file "{0}"'.format(file_name))

        # Analyzing band test for this file
        duration, pss, new_nu, new_data, norm_data, cf_det, bw_det = AnalyzeBandTest(
            args.polarimeter_name, file_name, args.output_path)

        # Producing preliminary plots
        preliminary_plots(args.polarimeter_name, new_nu,
                          new_data, args.output_path, pss, i)

        # Saving normalized data for both phase-switch status
        central_nu_det.append(cf_det)
        bandwidth_det.append(bw_det)
        norm_data_list.append(norm_data)
        PSStatus.append(pss)

    log.info(
        'Computed bandwidth and central frequency for each detector for both phase-switch status')

    central_nu_det = np.array(central_nu_det)
    bandwidth_det = np.array(bandwidth_det)
    norm_data_All = np.column_stack(norm_data_list)

    All_central_nu, All_bandwidth = get_central_nu_bandwidth(
        new_nu, norm_data_All)

    # Computing the final band
    final_band = np.median(norm_data_All, axis=1)
    final_band_err = (np.percentile(
        norm_data_All, 97.7, axis=1) - np.percentile(norm_data_All, 2.7, axis=1)) / 2

    # Producing final plots
    final_plots(args.polarimeter_name, new_nu, norm_data_All,
                final_band, final_band_err, args.output_path)

    # Computing final central frequency and final bandwidth
    final_central_nu, final_bandwidth = get_central_nu_bandwidth(
        new_nu, final_band[:, None])

    # Computing errors for central frequency and bandwidth
    final_central_nu_err = (np.percentile(
        All_central_nu, 97.7) - np.percentile(All_central_nu, 2.7)) / 2
    final_bandwidth_err = (np.percentile(
        All_bandwidth, 97.7) - np.percentile(All_bandwidth, 2.7)) / 2

    log.info(
        'Computed final bandwidth and final central frequency')

    # Creating the report
    params = build_dict_from_results(
        args.polarimeter_name, duration, PSStatus, central_nu_det, bandwidth_det,
        final_central_nu, final_central_nu_err,
        final_bandwidth, final_bandwidth_err)

    save_parameters_to_json(params=dict(params, **get_code_version_params()),
                            output_file_name=os.path.join(args.output_path,
                                                          'bandwidth_results.json'))

    create_report(params=params,
                  md_template_file='bandwidth.md',
                  md_report_file='bandwidth_report.md',
                  html_report_file='bandwidth_report.html',
                  output_path=args.output_path)


if __name__ == '__main__':
    main()