import pathlib
import re

import jinja2

from .parse_av_class import parse_av_class
from .parse_av_filter import parse_av_filter
from .parse_av_filter_pad import parse_av_filter_pad
from .parse_av_option import parse_av_option
from .parse_init import parse_init
from .schema import AVFilter, AVFilterPad

template_path = pathlib.Path(__file__).parent / "templates"


def parse_c(path: pathlib.Path) -> list[AVFilter]:
    with path.open() as f:
        code = f.read()

    # FIXME: remove MARCO preprocessor
    macro_pattern = r'WIN_FUNC_OPTION\("([^"]+)", ([^,]+), ([^,]+), ([^)]+)\)'

    def win_func_option(win_func_opt_name, win_func_offset, flag, default_window_func) -> str:
        with (template_path / "win_func_option.tmpl").open() as ifile:
            return jinja2.Template(ifile.read()).render(
                win_func_opt_name=win_func_opt_name,
                win_func_offset=win_func_offset,
                flag=flag,
                default_window_func=default_window_func,
            )

    # Function to perform the replacement
    def replace_macro(match):
        win_func_opt_name = match.group(1)
        win_func_offset = match.group(2)
        flag = match.group(3)
        default_window_func = match.group(4)
        return win_func_option(win_func_opt_name, win_func_offset, flag, default_window_func)

    # Replace the macro in the string
    code = re.sub(macro_pattern, replace_macro, code)
    return extract_av_filter(code)


def eval_offset(text: str) -> tuple[str, int]:
    if text == "((void*)0)":
        return None, 0

    matches = re.findall("([\w\_]+)\[(.*)\]", text)
    if len(matches) == 1:
        name, expression = matches[0]

        # Replace C-style logical operators with Python equivalents
        expression = expression.replace("||", "or").replace("&&", "and")

        # Evaluate the expression
        try:
            result = eval(expression, {"__builtins__": None}, {})
        except Exception as e:
            raise ValueError(f"Invalid expression: {expression}") from e

        # Ensure the result is an integer
        if not isinstance(result, int):
            raise ValueError("The expression does not evaluate to an integer")
        return name, result
    return text, 0


# const AVFilterPad ff_audio_default_filterpad[1] = {
#     {
#         .name = "default",
#         .type = AVMEDIA_TYPE_AUDIO,
#     }
# };

# const AVFilterPad ff_video_default_filterpad[1] = {
#     {
#         .name = "default",
#         .type = AVMEDIA_TYPE_VIDEO,
#     }
# };

default_filter_pads: dict[str, list[AVFilterPad]] = {
    "ff_audio_default_filterpad": [AVFilterPad(name="default", type="AVMEDIA_TYPE_AUDIO")],
    "ff_video_default_filterpad": [AVFilterPad(name="default", type="AVMEDIA_TYPE_VIDEO")],
}


def extract_av_filter(text: str) -> list[AVFilter]:
    output = []
    av_options = parse_av_option(text)
    av_filters = parse_av_filter(text)
    av_classes = parse_av_class(text)
    av_filter_pads = parse_av_filter_pad(text) | default_filter_pads

    for av_filter in av_filters.values():
        if av_filter.priv_class:
            av_class = av_classes[av_filter.priv_class_value]
            if av_class.option:
                option_name, offset = eval_offset(av_class.option)
                if option_name:
                    av_option = av_options[option_name][offset:]
                    av_filter.options = av_option

        if av_filter.inputs_value:
            av_filter.input_filter_pads = av_filter_pads[av_filter.inputs_value]

        if av_filter.outputs_value:
            av_filter.output_filter_pads = av_filter_pads[av_filter.outputs_value]

        if av_filter.init and (av_filter.is_dynamic_inputs or av_filter.is_dynamic_outputs):
            av_filter.init_src = parse_init(text, av_filter.init_value)

        output.append(av_filter)

    return output


def parse_all_filter_names(path: pathlib.Path) -> list[tuple[str, str, str]]:
    with path.open() as f:
        code = f.read()

    output = []
    for line in re.findall(r"extern const AVFilter ([\w\_]+);", code):
        _, flag, name = line.split("_", 2)
        output.append((flag, name, line))

    return output
