import sys, os
import doctest

def main():

    tests_dir = "tests"
    failure_count = 0
    for testfile in os.listdir(tests_dir):
        if os.path.splitext(testfile)[1] != ".txt":
            continue

        print testfile
        failure_count, test_count = doctest.testfile(
            os.path.join(tests_dir, testfile))

        if failure_count > 0:
            break

    return failure_count


if(__name__ == '__main__'):
    sys.exit( main() )
