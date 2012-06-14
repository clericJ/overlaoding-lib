# -*- coding: utf-8 -*-
# Name:        overloading.py
# Version:     0.7.2
# Author:      cleric
# Email:       py.cleric at google.com
# Created:     01.11.2007
# Updated:     24.12.2008
# Licence:     3-clause BSD

""" Модуль определяет средства реализующие парадигму обобщенного
программирования, добавляя в язык динамически перегружаемые функции

Для определения перегруженной функции/метода существуют
декораторы overload, и when, overload служит для
определения перегруженной функции, сигнатура
задается в параметрах декоратора, пример:

    @overload(float)
    def func(x):
        ...
    @overload(int)
    def func(x):
        ...

    func(1)         # вызов функции с сигнатурой func(x: int)
    func(1.0)       # вызов функции с сигнатурой func(x: float)

При разрешении перегрузки используется полиморфизм:

    class MyStr(str): pass

    @overload(str)
    def func(x):
        ...

    func("string")  # вызов функции с сигнатурой func(x: str)
    func(MyStr())   # вызов функции с сигнатурой func(x: str)

Декоратор overload в комбинации с mix-in классом Overloadable
позволяет определять перегруженные методы, семантика аналогична
использованию overload для функций (за исключением того что
в сигнатуру метода не входит первый параметр self), пример:

    class T(Overloadable):

        @overload(bool)
        def meth(self, x):
            ...
        @overload(int, str)
        def meth(self, x, y):
            ...
    i=T()
    i.meth(1, 'hello') # вызов метода с сигнатурой meth(x: int, y: str)
    i.meth(True)       # вызов метода с сигнатурой meth(x: bool)
    i.meth("Opps!")    # исключение CannotResolve, метод с сигнатурой
                       # meth(x: str) не определен

Декоратор when позволяет определить перегруженную функцию/метод
имя которой не совпадает с именем других перегруженных методов, пример:

    @overload(bool)
    def func(x):
        ...
    @overload(int)
    def func(x):
        ...
    @when(func, (list,))
    def func_list(x):
        ...

    func(1)         # вызов функции с сигнатурой func(x: int)
    func(True)      # вызов функции с сигнатурой func(x: bool)
    func([1,2,3])   # вызов функции определенной с помощью декоратора when
    func_list([1])  # явный вызов функции

Первым параметром декоратора должна быть перегруженная функция/метод,
определенная ранее в данном пространстве имен, второй параметр кортеж из
типов аргументов функции.

Определение обобщенной функции:

    # Обобщенная функция
    def func(x):
        ...

    # Специализированные функции

    @overload(int)
    def func(x):
        ...
    @overload(float)
    def func(x):
        ...
    func(1)         # вызов функции с сигнатурой func(x: int)
    func(1.0)       # вызов функции с сигнатурой func(x: float)
    func([1,2,3])   # вызов обобщенной функции

Обобщенная функция должна быть определена раньше её специализированных вариантов
и в том же пространстве имен

Ограничения:
- Нет поддержки аргументов со значениями по умолчанию
- Нет поддержки переменного числа аргументов (*args)
- Нет поддержки именованных аргументов (**kwargs)
- Нет приведения типов, например int не будет приведен к float
- Декораторы overload и when несовместимы с любыми другими декораторами
  включая classmethod и staticmethod
"""

# TODO: N50 реализовать функцию next для вызова из тела перегруженной функции
# менее специфичных функций

# TODO: N60 добавить метод __repr__ к _Dispatcher (сделано)
# TODO: N70 добавить больше проверок некоректных данных переданных в декораторы
# overload и when

# TODO: N80 если в параметре signature, функций overload и when встречается кортеж
# то считать что параметр соответствует одному из типов перечислинных в кортеже
# пример:
#
# overload( (list, dict), int )
# def f(collection, n):
#    ...
#
# тут функция вызовится если параметр collection будет list или dict


# FIXME: E120 если задать две функции с одинаковыми сигнатурами, одну с помощью
# overload другую с помощью when (имя должно отличатся) не показывается
# предупреждение о двух функциях с одинаковыми сигнатурами

import sys
from itertools import izip as _izip
from itertools import imap as _imap
import warnings as _warnings

from pprint import pprint

__all__ = ["AmbiguousFunctions", "CannotResolve", "get_function_by_signature",
           "is_overloaded", "overload", "when", "Overloadable",
           "OverloadableMeta"]

__debugprint__ = False
__disablewarnings__ = False
__usepsyco__ = False


class CannotResolve(Exception):
    '''
    Класс исключения возбуждаемый в случае ненахождения подходящей
    перегруженной функции
    '''
    pass


class AmbiguousFunctions(Exception):
    '''
    Класс исключения возбуждаемый при невозможности разрешить перегрузку
    ввиду неоднозначности выбора из функции кандидатов
    '''
    pass


def get_function_by_signature(overloaded, signature):
    '''
    Получение специализированной функции по её сигнатуре

    overloaded - перегруженная функция
    signature  - кортеж из типов параметров передаваемых функции
    return     - если функция найдена то оригинальная функция иначе None,
                 так же результатом будет None если выбор неоднозначен
    '''
    if not is_overloaded(overloaded):
        raise TypeError("Function '%s' not overloaded" % overloaded.__name__)
    try:
        return overloaded.dispatcher.resolve(signature)

    except AmbiguousFunctions:
        return None


def is_overloaded(function):
    '''
    Вспомогательная функция помогающая определить является ли
    переданная в первом аргументе функция перегруженной
    '''
    return(hasattr(function, "dispatcher")
        and isinstance(function.dispatcher, _Dispatcher))


def _calculate_number_of_ancestors(cls, root):
    '''
    Вспомогательная функция помогающая узнать количество предков
    cls, подсчет продолжается вплоть до root
    '''
    if cls is root:
        return 0

    result = 0
    while cls is not root:
        bases = cls.__bases__
        if len(bases) < 2:
            if not bases:
                return None

            cls = bases[0]
        else:
            best_data = [sys.maxint, None]
            for baseclass in bases:
                ancestor_count = _calculate_number_of_ancestors(baseclass, root)
                if(ancestor_count is not None) and (ancestor_count < best_data[0]):
                    best_data = (ancestor_count, baseclass)

            cls = best_data[1]

        result += 1
    return result


class _Dispatcher(object):

    def __init__(self, function, signature, generic_function=None):
        ''' Создание объекта разрешающего перегрузку функций/методов
        '''
        self._functions = {len(signature): [(function, signature)]}
        self.generic_function = generic_function
        self.name = function.__name__
        self.__cache = {}


    def register_generic(self, function, override=True):
        '''
        Регистрация функции в качестве обобщенной (функции по умолчанию)

        флаг override определяет поведение метода, если он равен True то
        ранее зарегистрированная обобщенная функция будет перезаписана
        функцией переданной в первом параметре
        '''
        if self.generic_function is not None:
            if __disablewarnings__ is False:
                _warnings.warn_explicit("Generic function '%s' overridden"\
                     % self.name, UserWarning, '', 0)

        if (self.generic_function is None) or override:
            self.generic_function = function


    def register_function(self, function, signature, override=True):
        '''
        Включение функции в разрешение перегрузки

        если функция с идентичной сигнатурой была зарегистрирована ранее
        флаг override определяет дальнейшее поведение, если флаг равен True
        то функция зарегистрированная ранее будет перезаписана функцией
        переданной в первом аргументе иначе функция переданная
        в первом параметре не будет зарегистрирована
        '''
        argcount = len(signature)
        already_registered = False

        if argcount not in self._functions:
            self._functions[argcount] = [(function, signature)]
        else:
            for index, (func, argtypes) in enumerate(self._functions[argcount]):
                if argtypes == signature:

                    self._show_equal_signatures_warning(signature, func, function)
                    already_registered = True

                    if override:
                        del self._functions[argcount][index]

            if (not already_registered) or (already_registered and override):
                self._functions[argcount].append((function, signature))


    def register_functions_from_dispatcher(self, dispatcher):
        ''' Регистрация функций из другого dispatcher'а
        '''
        for key, val in dispatcher._functions.iteritems():
            for function, signature, in val:
                self.register_function(function, signature, override=False)


    def _show_equal_signatures_warning(self, signature, *functions):
        ''' Показ предупреждения о идентичных сигнатурах
        '''
        if __disablewarnings__:
            return

        signstr = (", ".join(at.__name__ for at in signature))
        funcstr = []

        for function in functions:
            filename = function.func_code.co_filename
            lineno = function.func_code.co_firstlineno
            name = self.name

            funcstr.append(
                "%(filename)s:%(lineno)s:%(name)s(%(signstr)s)" % locals())

        templ = "Found overload functions with equal signatures:\n  %s"
        _warnings.warn_explicit(templ % "\n  ".join(funcstr),
            UserWarning, '', 0)


    def resolve(self, arg_types, disable_caching=False):
        '''
        Метод разрешающий перегрузку по заданным типам параметров

        возвращаемое значение - функция или None если невозможно разрешить
        перегрузку, если результат неоднозначен бросается
        исключение AmbiguousFunctions
        '''
        result = None
        candidates = []

        try:
            for candidate in self._functions[len(arg_types)]:
                for arg, argtype in _izip(arg_types, candidate[1]):
                    if not issubclass(arg, argtype):
                        break
                else:
                    candidates.append(candidate)

        except KeyError:
            pass

        if len(candidates) == 1:
            result = candidates[0][0]

        elif len(candidates) > 1:
            best_match = (sys.maxint, None)

            for (function, signature) in candidates:
                ancestor_count_sum = sum(
                    _imap(_calculate_number_of_ancestors, arg_types, signature))

                if best_match[0] > ancestor_count_sum:
                    best_match = (ancestor_count_sum, function)

                elif best_match[0] == ancestor_count_sum:
                    raise AmbiguousFunctions

            result = best_match[1]

        if (result is not None) and (not disable_caching):
            self.__cache[arg_types] = result

        return result


    def __call__(self, first, *args):
        arg_types = tuple(map(type, args))
        function = None

        if arg_types in self.__cache:
            function = self.__cache[arg_types]
        else:
            try:
                function = self.resolve(arg_types)

            except AmbiguousFunctions:
                raise AmbiguousFunctions(self._format_ambiguous_errmsg(args))

        if function is not None:
            if first is None:
                return function(*args)
            else:
                return function(first, *args)

        if self.generic_function is not None:
            self.__cache[arg_types] = self.generic_function
            if first is None:
                return self.generic_function(*args)
            else:
                return self.generic_function(first, *args)

        raise CannotResolve(self._format_cannot_resolve_errmsg(args))


    def _get_registered_functions_string(self):
        '''
        Получение строки содержащей информацию о всех перегруженных
        функциях участвующих в разрешении перегрузки, метод используется
        при формировании сообщения об ошибке
        '''
        functions = []
        for data in self._functions.itervalues():
            for (function, argtypes) in data:

                filename = function.func_code.co_filename
                lineno = function.func_code.co_firstlineno

                functions.append("%s:%s:%s(%s)" % (filename, lineno,
                    self.name, ", ".join(at.__name__ for at in argtypes)))
        return "\n  ".join(functions)


    def _format_cannot_resolve_errmsg(self, args):
        '''
        Вспомогательный метод форматирующий сообщение об ошибке CannotResolve
        '''
        templ = ("Can't found appropriate signature of function"
                 " '%s' for call with params %r\ncandidates:\n  %s")

        return templ % (self.name, args, self._get_registered_functions_string())


    def _format_ambiguous_errmsg(self, args):
        '''
        Вспомогательный метод форматирующий сообщение об ошибке AmbiguousFunctions
        '''
        templ = ("Call overloaded '%s' with params %r is ambiguous"
                 "\ncandidates:\n  %s")

        return templ % (self.name, args, self._get_registered_functions_string())


    def __repr__(self):
        generic_str = ""
        if self.generic_function is not None:
            g = self.generic_function
            generic_str = "\ngeneric:\n  %s:%s:%s(?)"% (g.func_code.co_filename,
                g.func_code.co_firstlineno, self.name)

        return "<dispatcher of %s at 0x%s> %s\nfunctions:\n  %s" % (self.name,
            hex(id(self)).upper(), generic_str,
            self._get_registered_functions_string())


def overload(*signature):
    '''
    Декоратор служит для определения перегруженной функции
    В случае определения метода, класс должен наследоваться от Overloadable

    Ограничения налагаемые на функцию:
    * функция должна принимать один или больше аргументов
    * параметры функции должны быть только позиционными

    signature - типы параметров передаваемых функции
    '''
    namespace = sys._getframe(1).f_locals

    def make_wrapper(func, signature, parent=None):
        dispatcher = None
        if parent is None:
            dispatcher = _Dispatcher(func, signature)
        else:
            dispatcher = _Dispatcher(func, signature, parent)

        result = ( lambda *args: dispatcher(None, *args) )
        result.__name__ = func.__name__
        result.dispatcher = dispatcher
        return result

    def decorator(func):
        if func.__name__ in namespace:
            parent = namespace[func.__name__]

            if is_overloaded(parent):
                parent.dispatcher.register_function(func, signature)
                result = parent
            else:
                result = make_wrapper(func, signature, parent)
        else:
            result = make_wrapper(func, signature)

        return result
    return decorator


def when(overloaded, signature):
    '''
    Декоратор для определения перегруженной функции
    под другим именем, в случае определения метода,
    класс должен наследоваться от Overloadable

    Ограничения налагаемые на функцию:
    * функция должна принимать один или больше аргументов
    * параметры функции должны быть только позиционными

    overloaded - перегруженная функция определенная в локальном пространстве имен
    signature - кортеж из типов параметров передаваемых функции
    '''
    namespace = sys._getframe(1).f_locals
    name = overloaded.__name__

    if name not in namespace:
        raise NameError("name '%s' is not defined in local namespace" % name)

    def decorator(func):
        if not is_overloaded(overloaded):
            raise TypeError("Function '%s' not overloaded" % overloaded.__name__)

        overloaded.dispatcher.register_function(func, signature)

        if(name == func.__name__):
            return overloaded

        return func
    return decorator


class OverloadableMeta(type):
    '''
    Метакласс назначение которого включить в разрешение
    перегрузки все перегруженные функции определенные в базовых классах
    '''

    def __init__(cls, clsname, bases, namespace):

        def replace_wrapper(wrapper):
            dispatcher = wrapper.dispatcher

            result = ( lambda *args: dispatcher(args[0], *args[1:]) )
            result.__name__ = wrapper.__name__
            result.dispatcher = dispatcher

            return result

        for name, attr in namespace.iteritems():
            if not is_overloaded(attr):
                continue

            attr = replace_wrapper(attr)
            setattr(cls, name, attr)

            for baseclass in bases:
                if name not in baseclass.__dict__:
                    continue

                if __debugprint__:
                    print "class", cls.__name__,
                    print "(", ", ".join([x.__name__ for x in bases]), ")"

                baseattr = baseclass.__dict__[name]
                if not is_overloaded(baseattr):
                    attr.dispatcher.register_generic(baseattr, override=False)

                elif attr.dispatcher != baseattr.dispatcher:

                    attr.dispatcher.register_functions_from_dispatcher(
                        baseattr.dispatcher)

                    attr.dispatcher.register_generic(
                        baseattr.dispatcher.generic_function, override=False)

                    if __debugprint__:
                        pprint(attr.dispatcher._functions)

        super(OverloadableMeta, cls).__init__(clsname, bases, namespace)


class Overloadable(object):
    '''
    Mix-in класс от которого должны наследоваться все классы
    в которых определенны перегруженные методы
    '''
    __metaclass__ = OverloadableMeta


if __usepsyco__:
    try:
        import psyco
    except ImportError:
        pass
    else:
        psyco.bind(_calculate_number_of_ancestors)
        psyco.bind(_Dispatcher.resolve)
        psyco.bind(_Dispatcher.__call__)
