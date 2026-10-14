<?php

namespace App\Filament\Resources;

use App\Filament\Resources\SiteResource\Pages;
use App\Models\Site;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Resources\Resource;
use Filament\Tables;
use Filament\Tables\Table;

class SiteResource extends Resource
{
    protected static ?string $model = Site::class;

    public static function form(Form $form): Form
    {
        return $form->schema([
            Forms\Components\TextInput::make('name')->required(),
        ]);
    }

    public static function table(Table $table): Table
    {
        return $table->columns([Tables\Columns\TextColumn::make('company.name'), Tables\Columns\TextColumn::make('name')])
            ->filters([]);
    }

    public static function getPages(): array
    {
        return [
            'index' => Pages\ManageSites::route('/'),
        ];
    }
}
