<?php

namespace App\Filament\Resources;

use App\Enums\OrderStatus;
use App\Filament\Resources\OrderResource\Pages;
use App\Models\Order;
use App\Models\Product;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Resources\Resource;
use Filament\Tables;
use Filament\Tables\Table;

class OrderResource extends Resource
{
    protected static ?string $model = Order::class;

    protected static ?string $navigationIcon = 'heroicon-o-shopping-cart';

    protected static ?string $navigationGroup = 'Shop';

    protected static ?string $recordTitleAttribute = 'number';

    public static function form(Form $form): Form
    {
        return $form->schema([
            Forms\Components\Tabs::make('Order')->tabs([
                Forms\Components\Tabs\Tab::make('Details')->schema([
                    Forms\Components\TextInput::make('number')
                        ->default(fn () => 'OR-' . random_int(100000, 999999))
                        ->disabled()
                        ->dehydrated()
                        ->required(),
                    Forms\Components\Select::make('customer_id')
                        ->relationship('customer', 'name')
                        ->searchable()
                        ->required(),
                    Forms\Components\ToggleButtons::make('status')
                        ->inline()
                        ->options(OrderStatus::class)
                        ->required(),
                    Forms\Components\Textarea::make('notes')
                        ->rows(3)
                        ->hidden(fn (string $operation): bool => $operation === 'create')
                        ->columnSpan('full'),
                ])->columns(2),
                Forms\Components\Tabs\Tab::make('Items')->schema([
                    Forms\Components\Repeater::make('items')
                        ->relationship()
                        ->schema([
                            Forms\Components\Select::make('product_id')
                                ->label('Product')
                                ->options(Product::query()->pluck('name', 'id'))
                                ->required(),
                            Forms\Components\TextInput::make('qty')->numeric()->default(1)->required(),
                            Forms\Components\TextInput::make('unit_price')->numeric()->required(),
                        ])
                        ->orderColumn('sort')
                        ->columns(3),
                ]),
            ])->columnSpanFull(),
        ]);
    }

    public static function table(Table $table): Table
    {
        return $table
            ->columns([
                Tables\Columns\TextColumn::make('number')->searchable(),
                Tables\Columns\TextColumn::make('customer.name')->searchable(),
                Tables\Columns\TextColumn::make('status')->badge(),
                Tables\Columns\TextColumn::make('total')->money('usd', divideBy: 1)->sortable(),
                Tables\Columns\TextColumn::make('created_at')->label('Order date')->date()->sortable(),
            ])
            ->filters([
                Tables\Filters\SelectFilter::make('status')->options(OrderStatus::class)->multiple(),
            ])
            ->actions([Tables\Actions\EditAction::make()])
            ->bulkActions([Tables\Actions\DeleteBulkAction::make()])
            ->defaultSort('created_at', 'desc');
    }

    public static function getPages(): array
    {
        return [
            'index' => Pages\ListOrders::route('/'),
            'create' => Pages\CreateOrder::route('/create'),
            'edit' => Pages\EditOrder::route('/{record}/edit'),
        ];
    }
}
