// CPython boundary for the explicit, non-durable native production core.
#define PY_SSIZE_T_CLEAN
#include "engine.hpp"
#include <Python.h>

namespace {
struct Native {
  PyObject_HEAD axiom::Engine *engine;
  unsigned long owner;
  bool initializing;
};
struct State {
  PyObject *type;
};

PyObject *error() {
  try {
    throw;
  } catch (const std::bad_alloc &) {
    return PyErr_NoMemory();
  } catch (const std::length_error &e) {
    PyErr_SetString(PyExc_MemoryError, e.what());
  } catch (const std::invalid_argument &e) {
    PyErr_SetString(PyExc_ValueError, e.what());
  } catch (const std::exception &e) {
    PyErr_SetString(PyExc_RuntimeError, e.what());
  }
  return nullptr;
}

bool number(PyObject *object, uint64_t &value) {
  if (!PyLong_Check(object) || PyBool_Check(object)) {
    PyErr_SetString(PyExc_ValueError, "expected a nonnegative integer");
    return false;
  }
  value = PyLong_AsUnsignedLongLong(object);
  if (PyErr_Occurred()) {
    PyErr_Clear();
    PyErr_SetString(PyExc_ValueError, "expected a nonnegative uint64 integer");
    return false;
  }
  return true;
}

bool guard(Native *self, bool query = false) {
  if (!self->engine || self->engine->graph().poisoned) {
    PyErr_SetString(PyExc_RuntimeError,
                    "native engine is unavailable or poisoned");
    return false;
  }
  if (self->owner && self->owner != PyThread_get_thread_ident()) {
    PyErr_SetString(PyExc_RuntimeError,
                    "engine transaction is owned by another thread");
    return false;
  }
  if (query && self->engine->graph().active) {
    PyErr_SetString(PyExc_RuntimeError,
                    "queries cannot observe an unpublished engine transaction");
    return false;
  }
  return true;
}

PyObject *create(PyTypeObject *type, PyObject *args, PyObject *kwargs) {
  static const char *names[] = {"n", "budget", nullptr};
  PyObject *n, *budget = nullptr;
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|$O:Engine",
                                   const_cast<char **>(names), &n, &budget))
    return nullptr;
  uint64_t vertices, limit = axiom::defaultBudget;
  if (!number(n, vertices) || (budget && !number(budget, limit)))
    return nullptr;
  if (vertices > axiom::none) {
    PyErr_SetString(PyExc_ValueError,
                    "vertex universe exceeds uint32 addressing");
    return nullptr;
  }
  auto *self = reinterpret_cast<Native *>(type->tp_alloc(type, 0));
  if (!self)
    return nullptr;
  try {
    self->engine = new axiom::Engine(static_cast<uint32_t>(vertices), limit);
  } catch (...) {
    Py_DECREF(self);
    return error();
  }
  self->initializing = true;
  return reinterpret_cast<PyObject *>(self);
}
int finish(Native *self, PyObject *, PyObject *) {
  if (!self->initializing) {
    PyErr_SetString(PyExc_RuntimeError, "engine cannot be reinitialized");
    return -1;
  }
  self->initializing = false;
  return 0;
}
void destroy(Native *self) {
  auto *type = Py_TYPE(self);
  delete self->engine;
  type->tp_free(reinterpret_cast<PyObject *>(self));
  Py_DECREF(type);
}
PyObject *size(Native *self, void *) {
  return PyLong_FromUnsignedLong(self->engine->graph().n);
}
PyObject *version(Native *self, void *) {
  return guard(self, true)
             ? PyLong_FromUnsignedLongLong(self->engine->graph().version)
             : nullptr;
}

bool endpoints(Native *self, PyObject *args, uint32_t &u, uint32_t &v) {
  PyObject *left, *right;
  uint64_t a, b;
  if (!guard(self) || !PyArg_ParseTuple(args, "OO", &left, &right) ||
      !number(left, a) || !number(right, b))
    return false;
  if (a > axiom::none || b > axiom::none) {
    PyErr_SetString(PyExc_ValueError, "vertex out of range");
    return false;
  }
  u = static_cast<uint32_t>(a);
  v = static_cast<uint32_t>(b);
  return true;
}
PyObject *edit(Native *self, PyObject *args, bool adding) {
  uint32_t u, v;
  if (!endpoints(self, args, u, v))
    return nullptr;
  try {
    return PyBool_FromLong(adding ? self->engine->insert(u, v)
                                  : self->engine->remove(u, v));
  } catch (...) {
    if (!self->engine->graph().active)
      self->owner = 0;
    return error();
  }
}
PyObject *insert(Native *self, PyObject *args) {
  return edit(self, args, true);
}
PyObject *remove(Native *self, PyObject *args) {
  return edit(self, args, false);
}
PyObject *partner(Native *self, PyObject *arg) {
  uint64_t vertex;
  if (!guard(self, true) || !number(arg, vertex))
    return nullptr;
  if (vertex >= self->engine->graph().n) {
    PyErr_SetString(PyExc_ValueError, "vertex out of range");
    return nullptr;
  }
  uint32_t result = self->engine->partner(static_cast<uint32_t>(vertex));
  if (result == axiom::none)
    Py_RETURN_NONE;
  return PyLong_FromUnsignedLong(result);
}
PyObject *count(Native *self, PyObject *) {
  return guard(self, true) ? PyLong_FromUnsignedLongLong(self->engine->size())
                           : nullptr;
}
PyObject *edges(Native *self, PyObject *) {
  return guard(self, true)
             ? PyLong_FromUnsignedLongLong(self->engine->graph().count)
             : nullptr;
}
PyObject *has(Native *self, PyObject *args) {
  if (!guard(self, true))
    return nullptr;
  uint32_t u, v;
  if (!endpoints(self, args, u, v))
    return nullptr;
  if (u >= self->engine->graph().n || v >= self->engine->graph().n) {
    PyErr_SetString(PyExc_ValueError, "vertex out of range");
    return nullptr;
  }
  return PyBool_FromLong(self->engine->graph().has(u, v));
}
PyObject *degree(Native *self, PyObject *arg) {
  uint64_t v;
  if (!guard(self, true) || !number(arg, v))
    return nullptr;
  if (v >= self->engine->graph().n) {
    PyErr_SetString(PyExc_ValueError, "vertex out of range");
    return nullptr;
  }
  return PyLong_FromUnsignedLong(
      self->engine->graph().degrees[static_cast<uint32_t>(v)]);
}
PyObject *check(Native *self, PyObject *) {
  if (!guard(self))
    return nullptr;
  try {
    return PyBool_FromLong(self->engine->check());
  } catch (...) {
    return error();
  }
}
PyObject *memory(Native *self, PyObject *) {
  auto wide = [](uint64_t value) {
    return static_cast<unsigned long long>(value);
  };
  return Py_BuildValue("{s:K,s:K,s:K,s:i,s:i}", "allocated",
                       wide(self->engine->allocated()), "budget",
                       wide(self->engine->budget()), "journal",
                       wide(self->engine->journal()), "active",
                       int(self->engine->graph().active), "poisoned",
                       int(self->engine->graph().poisoned));
}
PyObject *begin(Native *self, PyObject *) {
  if (!guard(self))
    return nullptr;
  try {
    uint64_t token = self->engine->begin();
    PyObject *result = PyLong_FromUnsignedLongLong(token);
    if (!result) {
      self->engine->rollback(token);
      return nullptr;
    }
    self->owner = PyThread_get_thread_ident();
    return result;
  } catch (...) {
    return error();
  }
}
PyObject *transaction(Native *self, PyObject *arg, bool committing) {
  uint64_t token;
  if (!guard(self) || !number(arg, token))
    return nullptr;
  try {
    if (committing)
      self->engine->commit(token);
    else
      self->engine->rollback(token);
    self->owner = 0;
  } catch (...) {
    return error();
  }
  Py_RETURN_NONE;
}
PyObject *commit(Native *self, PyObject *arg) {
  return transaction(self, arg, true);
}
PyObject *rollback(Native *self, PyObject *arg) {
  return transaction(self, arg, false);
}
PyObject *ring(Native *self, PyObject *args) {
  if (!guard(self))
    return nullptr;
  PyObject *arg = nullptr;
  uint64_t width = 2;
  if (!PyArg_ParseTuple(args, "|O", &arg) || (arg && !number(arg, width)))
    return nullptr;
  try {
    self->engine->ring(width);
  } catch (...) {
    return error();
  }
  Py_RETURN_NONE;
}

PyObject *page(Native *self, PyObject *args, PyObject *kwargs) {
  if (!guard(self, true))
    return nullptr;
  static const char *names[] = {"start", "limit", "version", nullptr};
  PyObject *a = nullptr, *b = nullptr, *c = nullptr;
  uint64_t start = 0, limit = 1024, expected = self->engine->graph().version;
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|OOO:page",
                                   const_cast<char **>(names), &a, &b, &c) ||
      (a && !number(a, start)) || (b && !number(b, limit)) ||
      (c && c != Py_None && !number(c, expected)))
    return nullptr;
  if (start > self->engine->graph().n || !limit || limit > 4096) {
    PyErr_SetString(PyExc_ValueError,
                    "start must be in [0,n]; page scans 1..4096 vertices");
    return nullptr;
  }
  if (expected != self->engine->graph().version) {
    PyErr_SetString(PyExc_RuntimeError, "stale matching page version");
    return nullptr;
  }
  uint64_t end = std::min(start + limit, uint64_t(self->engine->graph().n));
  PyObject *items = PyList_New(0);
  if (!items)
    return nullptr;
  for (uint64_t u = start; u < end; ++u) {
    uint32_t v = self->engine->partner(static_cast<uint32_t>(u));
    if (v != axiom::none && u < v) {
      PyObject *edge = Py_BuildValue("(II)", static_cast<uint32_t>(u), v);
      if (!edge || PyList_Append(items, edge) < 0) {
        Py_XDECREF(edge);
        Py_DECREF(items);
        return nullptr;
      }
      Py_DECREF(edge);
    }
  }
  PyObject *next = end < self->engine->graph().n
                       ? PyLong_FromUnsignedLongLong(end)
                       : Py_NewRef(Py_None);
  PyObject *version = PyLong_FromUnsignedLongLong(expected);
  if (!next || !version) {
    Py_XDECREF(next);
    Py_XDECREF(version);
    Py_DECREF(items);
    return nullptr;
  }
  PyObject *result = PyTuple_New(3);
  if (!result) {
    Py_DECREF(next);
    Py_DECREF(version);
    Py_DECREF(items);
    return nullptr;
  }
  PyTuple_SET_ITEM(result, 0, version);
  PyTuple_SET_ITEM(result, 1, items);
  PyTuple_SET_ITEM(result, 2, next);
  return result;
}

PyMethodDef methods[] = {
    {"insert", reinterpret_cast<PyCFunction>(insert), METH_VARARGS,
     "Insert a real edge and certify deterministic matching repair."},
    {"delete", reinterpret_cast<PyCFunction>(remove), METH_VARARGS,
     "Delete a real edge and certify deterministic matching repair."},
    {"partner", reinterpret_cast<PyCFunction>(partner), METH_O,
     "Read one committed partner."},
    {"size", reinterpret_cast<PyCFunction>(count), METH_NOARGS,
     "Read committed matching size."},
    {"num_edges", reinterpret_cast<PyCFunction>(edges), METH_NOARGS,
     "Read committed graph edge count."},
    {"has_edge", reinterpret_cast<PyCFunction>(has), METH_VARARGS,
     "Read committed edge membership."},
    {"degree", reinterpret_cast<PyCFunction>(degree), METH_O,
     "Read committed vertex degree."},
    {"check", reinterpret_cast<PyCFunction>(check), METH_NOARGS,
     "Independently audit graph, partner symmetry, count, and maximality."},
    {"memory", reinterpret_cast<PyCFunction>(memory), METH_NOARGS,
     "Report native allocation and transaction diagnostics."},
    {"begin", reinterpret_cast<PyCFunction>(begin), METH_NOARGS,
     "Open a private owner-bound graph/matching transaction."},
    {"commit", reinterpret_cast<PyCFunction>(commit), METH_O,
     "Publish one validated in-memory transaction; not a durable "
     "acknowledgment."},
    {"rollback", reinterpret_cast<PyCFunction>(rollback), METH_O,
     "Restore graph, partners, counts and logical version without allocation."},
    {"ring", reinterpret_cast<PyCFunction>(ring), METH_VARARGS,
     "Build and validate an isolated initial regular ring candidate."},
    {"page", reinterpret_cast<PyCFunction>(page), METH_VARARGS | METH_KEYWORDS,
     "Read a versioned matching page with bounded vertex scanning."},
    {nullptr, nullptr, 0, nullptr}};
PyGetSetDef getters[] = {{"n", reinterpret_cast<getter>(size), nullptr,
                          "Fixed vertex universe.", nullptr},
                         {"version", reinterpret_cast<getter>(version), nullptr,
                          "Committed real-mutation version.", nullptr},
                         {nullptr, nullptr, nullptr, nullptr, nullptr}};
PyType_Slot slots[] = {
    {Py_tp_new, reinterpret_cast<void *>(create)},
    {Py_tp_init, reinterpret_cast<void *>(finish)},
    {Py_tp_dealloc, reinterpret_cast<void *>(destroy)},
    {Py_tp_methods, methods},
    {Py_tp_getset, getters},
    {Py_tp_doc, const_cast<char *>("Explicit native maximal-matching core; "
                                   "persistence is not yet implemented.")},
    {0, nullptr}};
PyType_Spec spec = {"axiom.engine.Engine", sizeof(Native), 0,
                    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_IMMUTABLETYPE, slots};
int traverse(PyObject *module, visitproc visit, void *arg) {
  Py_VISIT(reinterpret_cast<State *>(PyModule_GetState(module))->type);
  return 0;
}
int clear(PyObject *module) {
  Py_CLEAR(reinterpret_cast<State *>(PyModule_GetState(module))->type);
  return 0;
}
int execute(PyObject *module) {
  auto *state = reinterpret_cast<State *>(PyModule_GetState(module));
  state->type = PyType_FromModuleAndSpec(module, &spec, nullptr);
  if (!state->type)
    return -1;
  Py_INCREF(state->type);
  if (PyModule_AddObject(module, "Engine", state->type) < 0) {
    Py_DECREF(state->type);
    return -1;
  }
  return 0;
}
PyModuleDef_Slot moduleSlots[] = {
    {Py_mod_exec, reinterpret_cast<void *>(execute)}, {0, nullptr}};
PyModuleDef definition = {PyModuleDef_HEAD_INIT,
                          "engine",
                          "Native matching core; not a durable service.",
                          sizeof(State),
                          nullptr,
                          moduleSlots,
                          traverse,
                          clear,
                          nullptr};
} // namespace
PyMODINIT_FUNC PyInit_engine() { return PyModuleDef_Init(&definition); }
