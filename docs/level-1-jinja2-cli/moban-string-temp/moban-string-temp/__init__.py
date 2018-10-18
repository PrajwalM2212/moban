import os
from collections import defaultdict
from lml.plugin import PluginInfo
from moban.hashstore import HASH_STORE
import moban.utils as utils
import moban.constants as constants
import moban.exceptions as exceptions
import moban.reporter as reporter
from string import Template


@PluginInfo(
    constants.TEMPLATE_ENGINE_EXTENSION, tags=["stmp"]
)
class StringTemplateEngine(object):
    def __init__(self, template_dirs, context_dirs):
        verify_the_existence_of_directories(template_dirs)
        self.context = Context(context_dirs)
        self.template_dirs = template_dirs
        self.__file_count = 0
        self.__templated_count = 0

    def render_to_file(self, template_file, data_file, output_file):
        template = Template(open(template_file).read())
        data = self.context.get_data(data_file)
        reporter.report_templating(template_file, output_file)

        rendered_content = template.substitute(**data)
        utils.write_file_out(output_file, rendered_content)
        self._file_permissions_copy(template_file, output_file)

    def render_to_files(self, array_of_param_tuple):
        sta = Strategy(array_of_param_tuple)
        sta.process()
        choice = sta.what_to_do()
        # based on choice decide what to do
        if choice == Strategy.DATA_FIRST:
            self._render_with_finding_data_first(sta.data_file_index)
        else:
            self._render_with_finding_template_first(sta.template_file_index)

    def report(self):
        if self.__templated_count == 0:
            reporter.report_no_action()
        elif self.__templated_count == self.__file_count:
            reporter.report_full_run(self.__file_count)
        else:
            reporter.report_partial_run(
                self.__templated_count, self.__file_count
            )

    def number_of_templated_files(self):
        return self.__templated_count

    def _render_with_finding_template_first(self, template_file_index):
        for (template_file, data_output_pairs) in template_file_index.items():
            for (data_file, output) in data_output_pairs:
                data = self.context.get_data(data_file)
                flag = self._apply_template(template_file, data, output)
                if flag:
                    reporter.report_templating(template_file, output)
                    self.__templated_count += 1
                self.__file_count += 1

    def _render_with_finding_data_first(self, data_file_index):
        for (data_file, template_output_pairs) in data_file_index.items():
            data = self.context.get_data(data_file)
            for (template_file, output) in template_output_pairs:
                flag = self._apply_template(template_file, data, output)
                if flag:
                    reporter.report_templating(template_file, output)
                    self.__templated_count += 1
                self.__file_count += 1

    def _apply_template(self, template_file, data, output):
        rendered_content = Template(open(template_file).read().strip()).substitute(**data)
        rendered_content = utils.strip_off_trailing_new_lines(rendered_content)
        rendered_content = rendered_content.encode("utf-8")
        flag = HASH_STORE.is_file_changed(
            output, rendered_content, template_file.filename
        )
        if flag:
            utils.write_file_out(
                output, rendered_content, strip=False, encode=False
            )
            utils.file_permissions_copy(template_file.filename, output)
        return flag

    def _file_permissions_copy(self, template_file, output_file):
        true_template_file = template_file
        for a_template_dir in self.template_dirs:
            true_template_file = os.path.join(a_template_dir, template_file)
            if os.path.exists(true_template_file):
                break
        utils.file_permissions_copy(true_template_file, output_file)

# specifically for data/config files
class Context(object):
    def __init__(self, context_dirs):
        verify_the_existence_of_directories(context_dirs)
        self.context_dirs = context_dirs
        self.__cached_environ_variables = dict(
            (key, os.environ[key]) for key in os.environ
        )

    def get_data(self, file_name):
        data = utils.open_yaml(self.context_dirs, file_name)
        utils.merge(data, self.__cached_environ_variables)
        return data


class Strategy(object):
    DATA_FIRST = 1
    TEMPLATE_FIRST = 2

    # data_file_index and template_file_index are dict of lists
    def __init__(self, array_of_param_tuple):
        self.data_file_index = defaultdict(list)
        self.template_file_index = defaultdict(list)
        self.tuples = array_of_param_tuple

    # All this is doing is dict[datafile] = (temp_file,out_file) and dict[temp_file] = (data_file,out_file)
    def process(self):
        for (template_file, data_file, output_file) in self.tuples:
            _append_to_array_item_to_dictionary_key(
                self.data_file_index, data_file, (template_file, output_file)
            )
            _append_to_array_item_to_dictionary_key(
                self.template_file_index,
                template_file,
                (data_file, output_file),
            )
    # Decide what should be first
    def what_to_do(self):
        choice = Strategy.DATA_FIRST
        # if data_file_index is empty then template first
        if self.data_file_index == {}:
            choice = Strategy.TEMPLATE_FIRST
        elif self.template_file_index != {}:
            # if template_file_index is not empty and data_files > template_files then template_first
            data_files = len(self.data_file_index)
            template_files = len(self.template_file_index)
            if data_files > template_files:
                choice = Strategy.TEMPLATE_FIRST
        return choice

# All this is doing is dict[datafile] = (temp_file,out_file) and dict[temp_file] = (data_file,out_file)
def _append_to_array_item_to_dictionary_key(adict, key, array_item):
    if array_item in adict[key]:
        raise exceptions.MobanfileGrammarException(
            constants.MESSAGE_SYNTAX_ERROR % (array_item, key)
        )
    else:
        adict[key].append(array_item)

# decide if directory exists
def verify_the_existence_of_directories(dirs):
    if not isinstance(dirs, list):
        dirs = [dirs]
    for directory in dirs:
        if os.path.exists(directory):
            continue
        should_I_ignore = (
            constants.DEFAULT_CONFIGURATION_DIRNAME in directory
            or constants.DEFAULT_TEMPLATE_DIRNAME in directory
        )
        if should_I_ignore:
            # ignore
            pass
        else:
            raise exceptions.DirectoryNotFound(
                constants.MESSAGE_DIR_NOT_EXIST % os.path.abspath(directory)
            )
