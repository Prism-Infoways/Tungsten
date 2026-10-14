<?php

namespace App\Filament\Resources;

use App\Filament\Resources\ProductResource\Pages;
use App\Models\Product;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Forms\Get;
use Filament\Forms\Set;
use Filament\Resources\Resource;
use Filament\Tables;
use Filament\Tables\Table;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\SoftDeletingScope;
use Illuminate\Support\Str;

class ProductResource extends Resource
{
    protected static ?string $model = Product::class;

    protected static ?string $navigationIcon = 'heroicon-o-shopping-bag';

    protected static ?string $navigationGroup = 'Shop';

    protected static ?int $navigationSort = 1;

    protected static ?string $recordTitleAttribute = 'name';

    public static function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\Group::make()
                    ->schema([
                        Forms\Components\Section::make('Details')
                            ->schema([
                                Forms\Components\TextInput::make('name')
                                    ->required()
                                    ->maxLength(255)
                                    ->live(onBlur: true)
                                    ->afterStateUpdated(fn (Set $set, ?string $state) => $set('slug', Str::slug($state))),
                                Forms\Components\TextInput::make('slug')
                                    ->required()
                                    ->unique(Product::class, 'slug', ignoreRecord: true)
                                    ->disabled()
                                    ->dehydrated(),
                                Forms\Components\TextInput::make('sku')->label('SKU')->maxLength(64),
                                Forms\Components\MarkdownEditor::make('description')->columnSpanFull(),
                            ])
                            ->columns(2),
                        Forms\Components\Section::make('Pricing')
                            ->schema([
                                Forms\Components\TextInput::make('price')
                                    ->numeric()
                                    ->prefix('$')
                                    ->minValue(0)
                                    ->required(),
                                Forms\Components\TextInput::make('quantity')
                                    ->numeric()
                                    ->default(0)
                                    ->rules(['integer', 'min:0']),
                            ])
                            ->columns(['sm' => 1, 'lg' => 2]),
                    ])
                    ->columnSpan(['lg' => 2]),
                Forms\Components\Section::make('Status')
                    ->schema([
                        Forms\Components\Toggle::make('is_visible')
                            ->label('Visible')
                            ->helperText(__('This product will be hidden from all sales channels.'))
                            ->default(true),
                        Forms\Components\DatePicker::make('published_at')
                            ->label('Availability')
                            ->default(now())
                            ->native(false),
                        Forms\Components\Select::make('category_id')
                            ->relationship('category', 'name')
                            ->searchable()
                            ->preload()
                            ->createOptionForm([Forms\Components\TextInput::make('name')]),
                        Forms\Components\Select::make('tags')
                            ->relationship(name: 'tags', titleAttribute: 'name')
                            ->multiple()
                            ->visible(fn (Get $get) => filled($get('category_id'))),
                        Forms\Components\FileUpload::make('image')
                            ->image()
                            ->directory('products')
                            ->maxSize(2048)
                            ->disk('public'),
                        Forms\Components\KeyValue::make('options')->hiddenOn('create'),
                    ])
                    ->columnSpan(['lg' => 1]),
                Forms\Components\ViewField::make('rating')->view('filament.forms.components.rating'),
            ])
            ->columns(3);
    }

    public static function table(Table $table): Table
    {
        return $table
            ->columns([
                Tables\Columns\ImageColumn::make('image')->circular(),
                Tables\Columns\TextColumn::make('name')
                    ->searchable()
                    ->sortable()
                    ->weight(\Filament\Support\Enums\FontWeight::Bold),
                Tables\Columns\TextColumn::make('category.name')->label('Category')->toggleable(),
                Tables\Columns\TextColumn::make('price')->money('usd')->sortable(),
                Tables\Columns\TextColumn::make('quantity')
                    ->numeric()
                    ->color(fn (int $state): string => $state < 10 ? 'danger' : 'success'),
                Tables\Columns\IconColumn::make('is_visible')->boolean()->label('Visible'),
                Tables\Columns\TextColumn::make('published_at')->date('d/m/Y')->toggleable(isToggledHiddenByDefault: true),
                Tables\Columns\TextColumn::make('updated_at')->since()->formatStateUsing(fn ($state) => $state->diffForHumans()),
            ])
            ->filters([
                Tables\Filters\SelectFilter::make('category')->relationship('category', 'name'),
                Tables\Filters\TernaryFilter::make('is_visible')->label('Visibility'),
                Tables\Filters\Filter::make('in_stock')->query(fn (Builder $query): Builder => $query->where('quantity', '>', 0)),
                Tables\Filters\Filter::make('cheap')->query(fn (Builder $query) => $query->whereHas('category', fn ($q) => $q)),
                Tables\Filters\TrashedFilter::make(),
            ])
            ->actions([
                Tables\Actions\ActionGroup::make([
                    Tables\Actions\ViewAction::make(),
                    Tables\Actions\EditAction::make(),
                    Tables\Actions\DeleteAction::make(),
                ]),
                Tables\Actions\Action::make('publish')
                    ->icon('heroicon-o-check')
                    ->action(fn (Product $record) => $record->update(['is_visible' => true])),
            ])
            ->bulkActions([
                Tables\Actions\BulkActionGroup::make([
                    Tables\Actions\DeleteBulkAction::make(),
                    Tables\Actions\RestoreBulkAction::make(),
                ]),
            ])
            ->defaultSort('name', 'asc')
            ->emptyStateHeading('No products yet')
            ->deferLoading();
    }

    public static function getRelations(): array
    {
        return [];
    }

    public static function getPages(): array
    {
        return [
            'index' => Pages\ListProducts::route('/'),
            'create' => Pages\CreateProduct::route('/create'),
            'edit' => Pages\EditProduct::route('/{record}/edit'),
        ];
    }

    public static function getEloquentQuery(): Builder
    {
        return parent::getEloquentQuery()
            ->withoutGlobalScopes([
                SoftDeletingScope::class,
            ]);
    }

    public static function getGloballySearchableAttributes(): array
    {
        return ['name', 'sku'];
    }
}
