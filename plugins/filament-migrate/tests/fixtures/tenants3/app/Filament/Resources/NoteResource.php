<?php

namespace App\Filament\Resources;

use App\Filament\Resources\NoteResource\Pages;
use App\Models\Note;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Resources\Resource;
use Filament\Tables;
use Filament\Tables\Table;

class NoteResource extends Resource
{
    protected static ?string $model = Note::class;

    public static function form(Form $form): Form
    {
        return $form->schema([
            Forms\Components\TextInput::make('body')->required(),
        ]);
    }

    public static function table(Table $table): Table
    {
        return $table->columns([Tables\Columns\TextColumn::make('owner.name'), Tables\Columns\TextColumn::make('booking.name'), Tables\Columns\TextColumn::make('body')])
            ->filters([Tables\Filters\SelectFilter::make('owner_id')->relationship('owner', 'name')]);
    }

    public static function getPages(): array
    {
        return [
            'index' => Pages\ManageNotes::route('/'),
        ];
    }
}
