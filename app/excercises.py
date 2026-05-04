#!python3
# Copyright 2026 Christopher T. Haynes. See the project LICENSE file.

# Thanks to https://rhythmarise.com/rhythm-vocabulary/ for these patterns.

from pprint import pprint

voicing_code = {  # voicing characters are the keys below
    'x': 'any',
    'B': 'base',
    'l': 'low',
    'h': 'high',
    's': 'slap',
    '.': 'ghost note'
}
voicing_characters = ''.join(list(voicing_code.keys()))

# exercises_text is a sequence of exercises separated by `---`.
# Each exercise consists of a name line followed by one or more patterns.
# Each pattern begins with a subdivision line followed by one or more
# measure lines. A subdivision line consists of sequential beat integers separated
# by one letter for each measure subdivision. A space follows these letters
# for readability unless the beat integer has two digits. A pattern line is a
# sequence of voicing character that line up with the corresponding subdivision's
# letters or beat integer. Multiple pattern lines in a measure line group share the
# same subdivision line.
# TODO add more patterns
# todo ghost notes . instead of space
exercises_text = """
3,3,2 (tresillo)
1e&a2e&a
x..x..x.
---
3,2,3
1 e & a 2 e & a
x     x   x
---
3/2 Clave
1 e & a 2 e & a 3 e & a 4 e & a
x     x     x       x   x
---
Gravity Grooves
1 e & a 2 e & a 3 e & a 4 e & a
B
B   B
B B B
B                           B
B                           B B
---
Susan's Groove
1 e & a 2 e & a 3 e & a 4 e & a 5 e & a 6 e & a 7 e & a 8 e & a
B   h       h   B   h B     h h B   h       h   B B B B B   h h
---
Pulses
1 & a 2 & a 3 & a 4 & a
B x x B x x B x x B x x
1 e & a 2 e & a 3 e & a 4 e & a
B x x x B x x x B x x x B x x x
1 & 2 & 3 & 4 & 5 & 6 &
B x B x B x B x B x B x
"""


# pattern: { beats_per_measure: int,
#            subdivisions_per_beat: int,
#            measures_per_pattern: int,
#            subdivision_line = str,
#            patterns: list(pattern_string)
#          }
# pattern_string: string of voicing characters of length subdivisions_per_beat *
#   beats_per_measure.
# exercise_dict: exercise_name -> list(pattern)
def make_exercises(text):  # -> (list(exercise_name), exercise_dict)
    exercise_name_list = []
    exercise_dict = {}
    for exercise_text in text.split('---'):
        lines = exercise_text.strip().splitlines()
        exercise_name = lines[0].strip()
        exercise_name_list.append(exercise_name)
        pattern_list = []
        subdivisions_per_beat = 0
        num_beats = 0
        patterns = []
        for line in lines[1:]:
            def error(message):
                raise SystemExit(
                    f"Error: {message} in exercise {exercise_name} line {line}"
                )

            line = line.strip()
            if not line:  # end of exercise
                break
            e_line = line[::2]  # only characters with even index
            if e_line[0] == '1':  # start a pattern
                if not ''.join(line[1::2].split()):
                    error('even position characters must be blank or a digit')
                patterns = []
                beat1, _ = e_line.split("2")
                subdivisions_per_beat = len(beat1)
                if not all(c.isdigit() for c in e_line[::subdivisions_per_beat]):
                    error('invalid subdivision line beat number')
                num_beats = int(len(e_line) / subdivisions_per_beat)
                if len(e_line) % subdivisions_per_beat != 0:
                    error('invalid subdivision line')
                pattern_list.append(
                    {'beats_per_measure': num_beats,
                     'subdivisions_per_beat': subdivisions_per_beat,
                     'subdivision_line': e_line,
                     'patterns': patterns
                     })
            else:
                if line[1::2].strip():
                    error('even position characters must be blank')
                elif not all(c in voicing_characters for c in e_line):
                    # characters with even index must be voicing codes
                    error('invalid voicing code')
                elif len(e_line) != subdivisions_per_beat * num_beats:
                    error('invalid pattern line length')
                patterns.append(e_line)
        exercise_dict[exercise_name] = pattern_list
    return exercise_name_list, exercise_dict


exercises = make_exercises(exercises_text)

if __name__ == '__main__':
    pprint(exercises)
    print('Done')

