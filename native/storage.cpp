// Native segmented graph storage. Python remains the algorithm/reference layer.
// Every accepted edge edit reserves all required blocks before changing either
// row.
#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <algorithm>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <unordered_set>
#include <vector>

#include "store.hpp"

namespace {
using axiom::Block;
using axiom::defaultBudget;
using axiom::none;
using axiom::Slot;
using axiom::Store;

struct Packed {
  PyObject_HEAD Store *graph;
  bool initializing;
  unsigned long owner;
};
struct Cursor {
  PyObject_HEAD Packed *owner;
  std::vector<uint32_t> *row;
  uint64_t version;
  uint32_t vertex;
  size_t position;
  bool edges;
  bool ended;
};
struct State {
  PyObject *packed;
  PyObject *cursor;
};

PyObject *error() {
  try {
    throw;
  } catch (const std::bad_alloc &) {
    return PyErr_NoMemory();
  } catch (const std::length_error &e) {
    PyErr_SetString(PyExc_MemoryError, e.what());
  } catch (const std::exception &e) {
    PyErr_SetString(PyExc_RuntimeError, e.what());
  }
  return nullptr;
}

bool number(PyObject *object, uint64_t &value, const char *message) {
  if (!PyLong_Check(object) || PyBool_Check(object)) {
    PyErr_SetString(PyExc_ValueError, message);
    return false;
  }
  value = PyLong_AsUnsignedLongLong(object);
  if (PyErr_Occurred()) {
    PyErr_Clear();
    PyErr_SetString(PyExc_ValueError, message);
    return false;
  }
  return true;
}

bool guard(Packed *self) {
  if (!self->graph) {
    PyErr_SetString(PyExc_RuntimeError, "uninitialized native graph");
    return false;
  }
  if (self->graph->poisoned) {
    PyErr_SetString(PyExc_RuntimeError,
                    "native storage is poisoned after a rollback failure");
    return false;
  }
  if (self->owner && self->owner != PyThread_get_thread_ident()) {
    PyErr_SetString(PyExc_RuntimeError,
                    "native transaction is owned by another thread");
    return false;
  }
  return true;
}

bool vertex(Packed *self, PyObject *object, uint32_t &value) {
  uint64_t wide;
  if (!guard(self))
    return false;
  if (!number(object, wide, "vertex must be an integer in the graph universe"))
    return false;
  if (wide >= self->graph->n) {
    PyErr_SetString(PyExc_ValueError, "vertex out of range");
    return false;
  }
  value = static_cast<uint32_t>(wide);
  return true;
}

int initialize(Packed *self, PyObject *args, PyObject *kwargs) {
  static const char *names[] = {"n", "budget", nullptr};
  PyObject *size, *limit = nullptr;
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O|$O:Packed",
                                   const_cast<char **>(names), &size, &limit))
    return -1;
  if (self->graph) {
    PyErr_SetString(PyExc_RuntimeError, "native graph cannot be reinitialized");
    return -1;
  }
  uint64_t n, budget = defaultBudget;
  if (!number(size, n, "n must be an integer in [0, 2**32-1]"))
    return -1;
  if (n > none) {
    PyErr_SetString(PyExc_ValueError, "native vertex address space exhausted");
    return -1;
  }
  if (limit && !number(limit, budget, "budget must be a nonnegative integer"))
    return -1;
  try {
    self->graph = new Store(static_cast<uint32_t>(n), budget);
  } catch (...) {
    error();
    return -1;
  }
  return 0;
}

PyObject *create(PyTypeObject *type, PyObject *args, PyObject *kwargs) {
  auto *self = reinterpret_cast<Packed *>(type->tp_alloc(type, 0));
  if (!self)
    return nullptr;
  if (initialize(self, args, kwargs) < 0) {
    Py_DECREF(self);
    return nullptr;
  }
  self->initializing = true;
  return reinterpret_cast<PyObject *>(self);
}
int finish(Packed *self, PyObject *, PyObject *) {
  if (!self->initializing) {
    PyErr_SetString(PyExc_RuntimeError, "native graph cannot be reinitialized");
    return -1;
  }
  self->initializing = false;
  return 0;
}
void destroy(Packed *self) {
  delete self->graph;
  PyTypeObject *type = Py_TYPE(self);
  type->tp_free(reinterpret_cast<PyObject *>(self));
  Py_DECREF(type);
}

PyObject *edit(Packed *self, PyObject *args, PyObject *kwargs, bool adding) {
  static const char *names[] = {"u", "v", "strict", nullptr};
  PyObject *left, *right;
  int strict = 0;
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "OO|$p",
                                   const_cast<char **>(names), &left, &right,
                                   &strict))
    return nullptr;
  uint32_t u, v;
  if (!vertex(self, left, u) || !vertex(self, right, v))
    return nullptr;
  if (u == v) {
    if (strict) {
      PyErr_SetString(PyExc_ValueError, "self-loops are not allowed");
      return nullptr;
    }
    Py_RETURN_NONE;
  }
  try {
    bool changed = adding ? self->graph->add(u, v) : self->graph->remove(u, v);
    if (!changed && strict) {
      PyErr_SetString(PyExc_ValueError,
                      adding ? "edge already exists" : "edge does not exist");
      return nullptr;
    }
  } catch (...) {
    return error();
  }
  Py_RETURN_NONE;
}
PyObject *add(Packed *self, PyObject *args, PyObject *kwargs) {
  return edit(self, args, kwargs, true);
}
PyObject *remove(Packed *self, PyObject *args, PyObject *kwargs) {
  return edit(self, args, kwargs, false);
}
PyObject *has(Packed *self, PyObject *args) {
  PyObject *left, *right;
  if (!PyArg_ParseTuple(args, "OO", &left, &right))
    return nullptr;
  uint32_t u, v;
  if (!vertex(self, left, u) || !vertex(self, right, v))
    return nullptr;
  return PyBool_FromLong(self->graph->has(u, v));
}
PyObject *degree(Packed *self, PyObject *arg) {
  uint32_t v;
  if (!vertex(self, arg, v))
    return nullptr;
  return PyLong_FromUnsignedLong(self->graph->degrees[v]);
}
PyObject *size(Packed *self, void *) {
  return PyLong_FromUnsignedLong(self->graph->n);
}
PyObject *version(Packed *self, void *) {
  return guard(self) ? PyLong_FromUnsignedLongLong(self->graph->version)
                     : nullptr;
}
PyObject *count(Packed *self, PyObject *) {
  return guard(self) ? PyLong_FromUnsignedLongLong(self->graph->count)
                     : nullptr;
}

State *state(Packed *self) {
  return reinterpret_cast<State *>(PyType_GetModuleState(Py_TYPE(self)));
}

void cursorDestroy(Cursor *self) {
  delete self->row;
  Py_XDECREF(self->owner);
  PyTypeObject *type = Py_TYPE(self);
  type->tp_free(reinterpret_cast<PyObject *>(self));
  Py_DECREF(type);
}
PyObject *cursorNext(Cursor *self) {
  if (self->ended)
    return nullptr;
  if (!guard(self->owner))
    return nullptr;
  if (self->version != self->owner->graph->epoch) {
    self->ended = true;
    PyErr_SetString(PyExc_RuntimeError,
                    "graph changed during native iteration");
    return nullptr;
  }
  try {
    for (;;) {
      while (self->position < self->row->size()) {
        uint32_t v = (*self->row)[self->position++];
        if (!self->edges)
          return PyLong_FromUnsignedLong(v);
        if (self->vertex < v)
          return Py_BuildValue("(II)", self->vertex, v);
      }
      if (!self->edges || self->vertex + 1 >= self->owner->graph->n) {
        self->ended = true;
        return nullptr;
      }
      ++self->vertex;
      *self->row = self->owner->graph->row(self->vertex);
      self->position = 0;
    }
  } catch (...) {
    self->ended = true;
    return error();
  }
}

PyObject *cursor(Packed *self, uint32_t v, bool edges) {
  auto *type = reinterpret_cast<PyTypeObject *>(state(self)->cursor);
  auto *result = reinterpret_cast<Cursor *>(type->tp_alloc(type, 0));
  if (!result)
    return nullptr;
  result->owner = self;
  Py_INCREF(self);
  result->version = self->graph->epoch;
  result->vertex = v;
  result->edges = edges;
  result->ended = edges && self->graph->n == 0;
  try {
    result->row = new std::vector<uint32_t>(
        result->ended ? std::vector<uint32_t>{} : self->graph->row(v));
  } catch (...) {
    Py_DECREF(result);
    return error();
  }
  return reinterpret_cast<PyObject *>(result);
}
PyObject *neighbors(Packed *self, PyObject *arg) {
  uint32_t v;
  return vertex(self, arg, v) ? cursor(self, v, false) : nullptr;
}
PyObject *edges(Packed *self, PyObject *) {
  return guard(self) ? cursor(self, 0, true) : nullptr;
}

PyObject *adopt(Packed *self, std::unique_ptr<Store> graph) {
  auto *result =
      reinterpret_cast<Packed *>(Py_TYPE(self)->tp_alloc(Py_TYPE(self), 0));
  if (!result)
    return nullptr;
  result->graph = graph.release();
  return reinterpret_cast<PyObject *>(result);
}
PyObject *empty(Packed *self, PyObject *) {
  if (!guard(self))
    return nullptr;
  try {
    return adopt(self,
                 std::make_unique<Store>(self->graph->n, self->graph->budget));
  } catch (...) {
    return error();
  }
}
PyObject *copy(Packed *self, PyObject *) {
  if (!guard(self))
    return nullptr;
  try {
    auto result = std::make_unique<Store>(*self->graph);
    result->active = false;
    result->undo.clear();
    result->serial = 0;
    return adopt(self, std::move(result));
  } catch (...) {
    return error();
  }
}
PyObject *compact(Packed *self, PyObject *) {
  if (!guard(self))
    return nullptr;
  try {
    auto candidate = self->graph->compact();
    delete self->graph;
    self->graph = candidate.release();
  } catch (...) {
    return error();
  }
  Py_RETURN_NONE;
}
PyObject *check(Packed *self, PyObject *) {
  if (!guard(self))
    return nullptr;
  try {
    return PyBool_FromLong(self->graph->check());
  } catch (...) {
    return error();
  }
}
PyObject *memory(Packed *self, PyObject *) {
  const Store &g = *self->graph;
  auto wide = [](uint64_t value) {
    return static_cast<unsigned long long>(value);
  };
  return Py_BuildValue(
      "{s:K,s:K,s:K,s:K,s:K,s:K,s:K,s:K,s:K}", "allocated", wide(g.allocated()),
      "budget", wide(g.budget), "metadata", wide(Store::base(g.n)), "arena",
      wide(uint64_t(g.blocks.capacity()) * sizeof(Block)), "index",
      wide(uint64_t(g.index.slots.capacity()) * sizeof(Slot)), "liveblocks",
      wide(g.blocks.size() - g.spare), "freeblocks", wide(g.spare), "journal",
      wide(uint64_t(g.undo.capacity()) * sizeof(axiom::Undo)), "active",
      wide(g.active));
}
PyObject *begin(Packed *self, PyObject *) {
  if (!guard(self))
    return nullptr;
  try {
    uint64_t token = self->graph->begin();
    PyObject *result = PyLong_FromUnsignedLongLong(token);
    if (!result) {
      self->graph->rollback(token);
      return nullptr;
    }
    self->owner = PyThread_get_thread_ident();
    return result;
  } catch (...) {
    return error();
  }
}
PyObject *transaction(Packed *self, PyObject *arg, bool committing) {
  if (!guard(self))
    return nullptr;
  uint64_t token;
  if (!number(arg, token, "transaction token must be an integer"))
    return nullptr;
  try {
    if (committing)
      self->graph->commit(token);
    else
      self->graph->rollback(token);
    self->owner = 0;
  } catch (...) {
    return error();
  }
  Py_RETURN_NONE;
}
PyObject *commit(Packed *self, PyObject *arg) {
  return transaction(self, arg, true);
}
PyObject *rollback(Packed *self, PyObject *arg) {
  return transaction(self, arg, false);
}
PyObject *ring(Packed *self, PyObject *args) {
  if (!guard(self))
    return nullptr;
  if (self->graph->active) {
    PyErr_SetString(
        PyExc_RuntimeError,
        "ring publication is not allowed during a native transaction");
    return nullptr;
  }
  PyObject *arg = nullptr;
  if (!PyArg_ParseTuple(args, "|O", &arg))
    return nullptr;
  uint64_t width = 2;
  if (arg && !number(arg, width, "width must be a nonnegative integer"))
    return nullptr;
  if (self->graph->count) {
    PyErr_SetString(PyExc_ValueError,
                    "ring construction requires an empty graph");
    return nullptr;
  }
  if (width &&
      (self->graph->n < 3 || width > (uint64_t(self->graph->n) - 1) / 2)) {
    PyErr_SetString(PyExc_ValueError,
                    "ring width must be less than half the vertex universe");
    return nullptr;
  }
  try {
    auto candidate = self->graph->ring(width);
    delete self->graph;
    self->graph = candidate.release();
  } catch (...) {
    return error();
  }
  Py_RETURN_NONE;
}

PyMethodDef methods[] = {
    {"add_edge", reinterpret_cast<PyCFunction>(add),
     METH_VARARGS | METH_KEYWORDS,
     "Insert both endpoints after bounded reservation."},
    {"remove_edge", reinterpret_cast<PyCFunction>(remove),
     METH_VARARGS | METH_KEYWORDS,
     "Remove both endpoints after journal reservation."},
    {"has_edge", reinterpret_cast<PyCFunction>(has), METH_VARARGS,
     "Test edge membership."},
    {"degree", reinterpret_cast<PyCFunction>(degree), METH_O,
     "Return cached vertex degree."},
    {"neighbors", reinterpret_cast<PyCFunction>(neighbors), METH_O,
     "Iterate sorted neighbors at the current version."},
    {"edges", reinterpret_cast<PyCFunction>(edges), METH_NOARGS,
     "Stream canonical edges at the current version."},
    {"num_edges", reinterpret_cast<PyCFunction>(count), METH_NOARGS,
     "Return the cached undirected edge count."},
    {"empty", reinterpret_cast<PyCFunction>(empty), METH_NOARGS,
     "Create empty storage with the same universe and budget."},
    {"copy", reinterpret_cast<PyCFunction>(copy), METH_NOARGS,
     "Clone native storage independently."},
    {"compact", reinterpret_cast<PyCFunction>(compact), METH_NOARGS,
     "Publish a budget-checked compact candidate."},
    {"check", reinterpret_cast<PyCFunction>(check), METH_NOARGS,
     "Check symmetry, counts, and native block ownership."},
    {"memory", reinterpret_cast<PyCFunction>(memory), METH_NOARGS,
     "Report native retained-capacity accounting."},
    {"ring", reinterpret_cast<PyCFunction>(ring), METH_VARARGS,
     "Build a regular ring without Python edge materialization."},
    {"begin", reinterpret_cast<PyCFunction>(begin), METH_NOARGS,
     "Open an owner-bound mutation journal and return its token."},
    {"commit", reinterpret_cast<PyCFunction>(commit), METH_O,
     "Commit the token's mutation journal."},
    {"rollback", reinterpret_cast<PyCFunction>(rollback), METH_O,
     "Undo the token's edits without allocation and restore its version."},
    {nullptr, nullptr, 0, nullptr}};
PyGetSetDef getters[] = {{"n", reinterpret_cast<getter>(size), nullptr,
                          "Fixed vertex universe.", nullptr},
                         {"version", reinterpret_cast<getter>(version), nullptr,
                          "Accepted real-mutation version.", nullptr},
                         {nullptr, nullptr, nullptr, nullptr, nullptr}};
PyType_Slot packedSlots[] = {
    {Py_tp_doc,
     const_cast<char *>(
         "Compact, bounded, native segmented undirected graph storage.")},
    {Py_tp_new, reinterpret_cast<void *>(create)},
    {Py_tp_init, reinterpret_cast<void *>(finish)},
    {Py_tp_dealloc, reinterpret_cast<void *>(destroy)},
    {Py_tp_methods, methods},
    {Py_tp_getset, getters},
    {0, nullptr}};
PyType_Slot cursorSlots[] = {
    {Py_tp_doc, const_cast<char *>("Fail-fast native graph iterator.")},
    {Py_tp_dealloc, reinterpret_cast<void *>(cursorDestroy)},
    {Py_tp_iter, reinterpret_cast<void *>(PyObject_SelfIter)},
    {Py_tp_iternext, reinterpret_cast<void *>(cursorNext)},
    {0, nullptr}};
PyType_Spec packedSpec = {"axiom.storage.Packed", sizeof(Packed), 0,
                          Py_TPFLAGS_DEFAULT | Py_TPFLAGS_IMMUTABLETYPE,
                          packedSlots};
PyType_Spec cursorSpec = {"axiom.storage.Cursor", sizeof(Cursor), 0,
                          Py_TPFLAGS_DEFAULT | Py_TPFLAGS_IMMUTABLETYPE,
                          cursorSlots};

int traverse(PyObject *module, visitproc visit, void *arg) {
  auto *s = reinterpret_cast<State *>(PyModule_GetState(module));
  Py_VISIT(s->packed);
  Py_VISIT(s->cursor);
  return 0;
}
int clear(PyObject *module) {
  auto *s = reinterpret_cast<State *>(PyModule_GetState(module));
  Py_CLEAR(s->packed);
  Py_CLEAR(s->cursor);
  return 0;
}
PyObject *publish(PyObject *module, PyObject *participants) {
  if (!PyList_CheckExact(participants)) {
    PyErr_SetString(PyExc_TypeError,
                    "participants must be a list of graph/token pairs");
    return nullptr;
  }
  auto *s = reinterpret_cast<State *>(PyModule_GetState(module));
  const Py_ssize_t count = PyList_GET_SIZE(participants);
  // Validate every participant before closing any journal. No Python callback,
  // allocation, or throwing operation occurs in the publication pass.
  for (Py_ssize_t i = 0; i < count; ++i) {
    PyObject *pair = PyList_GET_ITEM(participants, i);
    if (!PyTuple_CheckExact(pair) || PyTuple_GET_SIZE(pair) != 2 ||
        Py_TYPE(PyTuple_GET_ITEM(pair, 0)) !=
            reinterpret_cast<PyTypeObject *>(s->packed)) {
      PyErr_SetString(PyExc_TypeError,
                      "participants must contain native graph/token pairs");
      return nullptr;
    }
    auto *graph = reinterpret_cast<Packed *>(PyTuple_GET_ITEM(pair, 0));
    uint64_t token;
    if (!guard(graph) ||
        !number(PyTuple_GET_ITEM(pair, 1), token, "invalid transaction token"))
      return nullptr;
    if (!graph->graph->active || graph->graph->serial != token) {
      PyErr_SetString(PyExc_RuntimeError, "invalid or stale transaction token");
      return nullptr;
    }
  }
  for (Py_ssize_t i = 0; i < count; ++i) {
    auto *graph = reinterpret_cast<Packed *>(
        PyTuple_GET_ITEM(PyList_GET_ITEM(participants, i), 0));
    graph->graph->undo.clear();
    graph->graph->active = false;
    graph->owner = 0;
  }
  Py_RETURN_NONE;
}
PyMethodDef moduleMethods[] = {
    {"publish", publish, METH_O,
     "Validate all participants, then commit without allocation."},
    {nullptr, nullptr, 0, nullptr}};
int execute(PyObject *module) {
  auto *s = reinterpret_cast<State *>(PyModule_GetState(module));
  s->cursor = PyType_FromModuleAndSpec(module, &cursorSpec, nullptr);
  s->packed = PyType_FromModuleAndSpec(module, &packedSpec, nullptr);
  if (!s->cursor || !s->packed)
    return -1;
  Py_INCREF(s->packed);
  if (PyModule_AddObject(module, "Packed", s->packed) < 0) {
    Py_DECREF(s->packed);
    return -1;
  }
  return 0;
}
PyModuleDef_Slot moduleSlots[] = {
    {Py_mod_exec, reinterpret_cast<void *>(execute)}, {0, nullptr}};
PyModuleDef definition = {PyModuleDef_HEAD_INIT,
                          "storage",
                          "Bounded native graph storage; the reference "
                          "matching engine remains Python.",
                          sizeof(State),
                          moduleMethods,
                          moduleSlots,
                          traverse,
                          clear,
                          nullptr};
} // namespace

PyMODINIT_FUNC PyInit_storage() { return PyModuleDef_Init(&definition); }
