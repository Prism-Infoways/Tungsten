"""The PHP reader and the closure translator."""

from __future__ import annotations

from tungsten_filament.closures import translate
from tungsten_filament.laravel import database_url, plural, singular, snake, table_for
from tungsten_filament.php import (
    Arr,
    ClassConst,
    Closure,
    MethodCall,
    PhpFile,
    Raw,
    StaticCall,
    chain,
    literal,
    parse_expr,
    tokenize,
)


def test_tokens_skip_comments_attributes_and_keep_strings():
    toks = tokenize("<?php #[Attr(['a' => 1])]\n// c\n/* x */ $a = 'it\\'s' . \"n\\n\";")
    kinds = [(t.kind, t.value) for t in toks if t.kind != "eof"]
    assert kinds == [("var", "a"), ("op", "="), ("str", "it's"), ("op", "."), ("str", "n\n"), ("op", ";")]


def test_chain_with_named_arguments():
    node = parse_expr("TextInput::make('name')->required()->live(onBlur: true)->maxLength(255)")
    base, calls = chain(node)
    assert isinstance(base, StaticCall) and base.cls == "TextInput" and literal(base.args[0].value) == "name"
    assert [c.method for c in calls] == ["required", "live", "maxLength"]
    assert calls[1].args[0].name == "onBlur" and literal(calls[1].args[0].value) is True


def test_unknown_code_is_kept_as_raw():
    node = parse_expr("['a' => $x + 1, 'b' => fn ($s) => $s, 'c' => Status::Paid, 'd' => Foo::class]")
    assert isinstance(node, Arr)
    values = [v for _, v in node.items]
    assert isinstance(values[0], Raw) and values[0].src == "$x + 1"
    assert isinstance(values[1], Closure)
    assert isinstance(values[2], ClassConst) and values[2].name == "Paid"
    assert isinstance(values[3], ClassConst) and values[3].name == "class"


def test_classes_uses_and_methods():
    php = PhpFile("""<?php
namespace App\\Models;
use Illuminate\\Database\\Eloquent\\{Model, SoftDeletes as Soft};
use App\\Enums\\Status;
final class Invoice extends Model {
    use Soft, HasFactory;
    protected $table = 'bills';
    const LIMIT = 10;
    public function lines() { return $this->hasMany(Line::class, 'bill_id'); }
    abstract protected function x();
}
""")
    cls = php.classes[0]
    assert cls.fqn == "App\\Models\\Invoice" and cls.resolve(cls.extends) == "Illuminate\\Database\\Eloquent\\Model"
    assert php.resolve("Soft") == "Illuminate\\Database\\Eloquent\\SoftDeletes"
    assert cls.traits == ["Soft", "HasFactory"]
    assert literal(cls.prop("table")) == "bills" and literal(cls.constants["LIMIT"]) == 10
    ret = cls.returns("lines")[0]
    assert isinstance(ret, MethodCall) and ret.method == "hasMany"


def test_enum_cases():
    php = PhpFile("<?php enum Size: int { case Small = 1; case Big = 2; public function label() { return 'x'; } }")
    cls = php.classes[0]
    assert cls.kind == "enum" and cls.backing == "int"
    assert [(n, literal(v)) for n, v in cls.cases] == [("Small", 1), ("Big", 2)]


def test_closures_translate_when_simple():
    def tr(src):
        out = translate(parse_expr(src), lambda cls, case: {"Paid": "paid"}.get(case))
        return out and out[0]

    assert tr("fn (Get $get) => $get('type') === 'company'") == "lambda get: (get('type') == 'company')"
    assert tr("fn ($record) => $record?->customer?->name ?? '-'") == (
        "lambda record: (getattr(getattr(record, 'customer', None), 'name', None) if "
        "getattr(getattr(record, 'customer', None), 'name', None) is not None else '-')")
    assert tr("fn ($state) => Status::Paid === $state") == "lambda state: ('paid' == state)"
    assert tr("fn (?string $state) => Str::slug($state)") == "lambda state: slug(state)"
    assert tr("fn ($state) => in_array($state, ['a', 'b'])") == "lambda state: (state in ['a', 'b'])"
    assert tr("function (Get $get) { return !$get('a') && $get('b') > 3; }") == \
        "lambda get: ((not get('a')) and (get('b') > 3))"
    # things we do not translate
    assert tr("fn ($record) => $record->total()") is None
    assert tr("fn (Livewire $livewire) => $livewire->x") is None
    assert tr("function ($s) use ($x) { return $x; }") is None
    assert tr("fn ($state) => match (true) { $state > 3 => 'a' }") is None


def test_laravel_naming():
    assert snake("OrderItem") == "order_item" and snake("HTMLPage") == "html_page"
    assert table_for("OrderItem") == "order_items" and table_for("Category") == "categories"
    assert table_for("Person") == "people" and table_for("Box") == "boxes" and table_for("Staff") == "staff"
    assert plural("address") == "addresses" and singular("categories") == "category"


def test_database_urls(tmp_path):
    assert database_url({"DB_CONNECTION": "pgsql", "DB_DATABASE": "app", "DB_USERNAME": "u", "DB_PASSWORD": "p"},
                        tmp_path)[0] == "postgresql+psycopg://u:p@127.0.0.1:5432/app"
    assert database_url({}, tmp_path)[0] == f"sqlite:///{(tmp_path / 'database/database.sqlite').resolve()}"
    assert database_url({"DB_URL": "mysql://a:b@h/db"}, tmp_path, mask_password=True)[0] == \
        "mysql+pymysql://a:***@h/db"
