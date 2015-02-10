import argparse
from collections import OrderedDict
import sys

import charts
import storage_api


def ssize_to_kb(ssize):
    try:
        smap = dict(k=1, K=1, M=1024, m=1024, G=1024**2, g=1024**2)
        for ext, coef in smap.items():
            if ssize.endswith(ext):
                return int(ssize[:-1]) * coef

        if int(ssize) % 1024 != 0:
            raise ValueError()

        return int(ssize) / 1024

    except (ValueError, TypeError, AttributeError):
        tmpl = "Unknow size format {0!r} (or size not multiples 1024)"
        raise ValueError(tmpl.format(ssize))


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--storage', help='storage location', dest="url")
    parser.add_argument('-e', '--email', help='user email',
                        default="aaa@gmail.com")
    parser.add_argument('-p', '--password', help='user password',
                        default="1234")
    return parser.parse_args(argv)


def build_vertical_bar(results):
    data = {}
    charts_url = []

    for build, results in results.items():
        for key, value in results.results.items():
            keys = key.split(' ')
            if not data.get(keys[2]):
                data[keys[2]] = {}
            if not data[keys[2]].get(build):
                data[keys[2]][build] = {}
            data[keys[2]][build][' '.join([keys[0], keys[1]])] = value

    scale_x_a = ['randwrite a', 'randread a', 'write a', 'read a']
    scale_x_s = ['randwrite s', 'randread s', 'write s', 'read s']

    for name, value in data.items():
        title = name
        legend = []
        dataset_s = []
        dataset_a = []

        for build_id, build_results in value.items():
            legend.append(build_id)
            # import pdb;pdb.set_trace()
            ordered_build_results_s = OrderedDict(
                sorted([(k, v) for k, v in build_results.items()
                       if k in scale_x_s], key=lambda t: scale_x_s.index(t[0])))
            ordered_build_results_a = OrderedDict(
                sorted([(k, v) for k, v in build_results.items()
                       if k in scale_x_a], key=lambda t: scale_x_a.index(t[0])))

            dataset_s.append(ordered_build_results_s.values())
            dataset_a.append(ordered_build_results_a.values())

        bar_s = charts.render_vertical_bar(title, legend, dataset_s,
                                           scale_x=scale_x_s)
        bar_a = charts.render_vertical_bar(title, legend, dataset_a,
                                           scale_x=scale_x_a)
        charts_url.extend([str(bar_s), str(bar_a)])
    return charts_url


def build_lines_chart(results):
    data = {}
    charts_url = []

    for build, results in results.items():
        for key, value in results.results.items():
            keys = key.split(' ')
            if not data.get(' '.join([keys[0], keys[1]])):
                data[' '.join([keys[0], keys[1]])] = {}
            if not data[' '.join([keys[0], keys[1]])].get(build):
                data[' '.join([keys[0], keys[1]])][build] = {}
            data[' '.join([keys[0], keys[1]])][build][keys[2]] = value

    for name, value in data.items():
        title = name
        legend = []
        dataset = []
        scale_x = []
        for build_id, build_results in value.items():
            legend.append(build_id)
            ordered_build_results = OrderedDict(sorted(build_results.items(),
                                                key=lambda t: ssize_to_kb(t[0])))
            if not scale_x:
                scale_x = ordered_build_results.keys()
            dataset.append(zip(*ordered_build_results.values())[0])

        chart = charts.render_lines(title, legend, dataset, scale_x)
        charts_url.append(str(chart))

    return charts_url


def render_html(charts_urls):
    templ = open("report.html", 'r').read()
    body = "<div><ol>%s</ol></div>"
    li = "<li><img src='%s'></li>"
    ol = []
    for chart in charts_urls:
        ol.append(li % chart)
    html = templ % {'body': body % '\n'.join(ol)}
    open('results.html', 'w').write(html)


def report(url, email=None, password=None):
    storage = storage_api.create_storage(url, email, password)
    results = storage.recent_builds()
    bars = build_vertical_bar(results)
    lines = build_lines_chart(results)

    render_html(bars + lines)


def main(argv):
    opts = parse_args(argv)
    report(opts.url)
    return 0


if __name__ == '__main__':
    exit(main(sys.argv[1:]))